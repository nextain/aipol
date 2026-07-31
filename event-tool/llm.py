"""LLM 디스패치 — 프로바이더 레지스트리(ai_config.PROVIDERS) 기반 범용.

프로바이더 추가: ai_config.PROVIDERS에 한 줄. OpenAI 호환이면 코드 수정 0.
특수 포맷(CLOVA 등)만 아래 _DISPATCH에 kind 분기 1개 추가.
"""
from __future__ import annotations

import json
import os
import urllib.request

import ai_config as CFG


def _post(url: str, body: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _openai_chat(spec: dict, model: str, messages: list, temperature: float) -> str:
    key = os.environ[spec["env"]]
    body = {"model": model, "messages": messages,
            "max_tokens": spec.get("max_tokens", 4000), "temperature": temperature}
    body.update(spec.get("extra") or {})
    d = _post(spec["base"] + "/chat/completions", body,
              {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    m = d["choices"][0]["message"]
    return (m.get("content") or m.get("reasoning_content") or "").strip()


def _clova_chat(spec: dict, model: str, messages: list, temperature: float) -> str:
    # CLOVA Studio(HCX) v3 — Bearer nv-키, /v3/chat-completions/{model}, 응답=result.message.content.
    key = os.environ[spec["env"]]
    body = {"messages": messages, "maxTokens": spec.get("max_tokens", 4000),
            "temperature": temperature, "topP": 0.8}
    d = _post(spec["base"] + f"/v3/chat-completions/{model}", body,
              {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return (d.get("result", {}).get("message", {}).get("content") or "").strip()


def _ollama_chat(spec: dict, model: str, messages: list, temperature: float) -> str:
    d = _post(spec["base"] + "/api/chat",
              {"model": model, "messages": messages, "stream": False, "think": False,
               "options": {"temperature": temperature, "num_predict": spec.get("max_tokens", 4000)}},
              {"Content-Type": "application/json"})
    return d["message"]["content"]


_DISPATCH = {"openai": _openai_chat, "clova": _clova_chat, "ollama": _ollama_chat}


def chat(model_entry: dict, messages: list, temperature: float = 0.7, tries: int = 5) -> str:
    """멀티턴 생성 + 429/5xx 백오프 재시도. model_entry = 로스터 항목 {provider, model, ...}."""
    import time
    import urllib.error
    spec = CFG.provider(model_entry["provider"])
    fn = _DISPATCH.get(spec["kind"])
    if not fn:
        raise ValueError(f"디스패치 없음: kind={spec['kind']}")
    for k in range(tries):
        try:
            return fn(spec, model_entry["model"], messages, temperature)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and k < tries - 1:
                time.sleep(4 * (k + 1)); continue
            raise


def ask(model_entry: dict, system: str, user: str, temperature: float = 0.7) -> str:
    """단일턴 편의."""
    return chat(model_entry, [{"role": "system", "content": system}, {"role": "user", "content": user}], temperature)


def extract_json(text: str) -> dict:
    import re
    if not text or not text.strip():
        raise ValueError("빈 응답")
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    blob = m.group(1) if m else text
    dec = json.JSONDecoder()
    for i, ch in enumerate(blob):
        if ch in "[{":
            try:
                return dec.raw_decode(blob[i:])[0]
            except json.JSONDecodeError:
                continue
    raise ValueError(f"JSON 못 찾음: {text[:80]!r}")
