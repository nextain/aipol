"""Create a review-only Korean draft with Upstage Solar.

This command is intentionally manual. It never discovers, publishes, commits or
merges content, and it only accepts a source packet prepared from an official
original. Keep ``UPSTAGE_API_KEY`` outside the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPT = Path(__file__).with_name("prompt.txt")
INBOX = ROOT / "content" / "global-ai-policy" / "_inbox"


def _default_private_env(root: Path) -> Path:
    """Find the optional workspace secret path without assuming parent depth."""
    for candidate in (root, *root.parents):
        if (candidate / "data-private").is_dir():
            return candidate / "data-private" / "key" / "llm-key.env"
    return root / "data-private" / "key" / "llm-key.env"


DEFAULT_PRIVATE_ENV = _default_private_env(ROOT)
ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
DEFAULT_MODEL = "solar-open2"
MAX_SOURCE_CHARS = 24_000
OUTPUT_FIELDS = {"title_ko", "summary_ko", "policy_use", "human_review", "relevance", "caveat"}
FIELD_CHAR_LIMITS = {
    "title_ko": 160,
    "summary_ko": 900,
    "policy_use": 600,
    "human_review": 600,
    "relevance": 600,
    "caveat": 600,
}
SOURCE_FIELDS = {"source_name", "source_url", "published", "country", "title", "source_text"}


def api_key_from_env_file(path: Path) -> str:
    """Read only the Upstage key without evaluating shell syntax."""
    if not path.is_file():
        return ""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        if name in {"UPSTAGE_API_KEY", "UPSTAGE_KEY"}:
            values[name] = value.strip().strip('"').strip("'")
    return values.get("UPSTAGE_API_KEY") or values.get("UPSTAGE_KEY", "")


def resolve_api_key() -> str:
    direct = os.getenv("UPSTAGE_API_KEY", "").strip() or os.getenv("UPSTAGE_KEY", "").strip()
    if direct:
        return direct
    env_file = Path(os.getenv("POLICY_LAB_LLM_ENV", DEFAULT_PRIVATE_ENV))
    return api_key_from_env_file(env_file)


def build_payload(packet: dict[str, str], model: str) -> dict:
    missing = SOURCE_FIELDS - set(packet)
    if missing:
        raise ValueError(f"missing source fields: {', '.join(sorted(missing))}")
    if not packet["source_url"].startswith("https://"):
        raise ValueError("source_url must use https")
    source_text = packet["source_text"].strip()
    if not source_text:
        raise ValueError("source_text must not be empty")
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ValueError(f"source_text exceeds {MAX_SOURCE_CHARS} characters")
    context = {key: packet[key] for key in ("source_name", "source_url", "published", "country", "title")}
    context["source_text"] = source_text
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        # Solar Open2 uses this shared budget for hidden reasoning and visible
        # output. A 4K budget can end at ``finish_reason=length`` before any
        # contract JSON becomes visible for a bounded 24K-character source.
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def call_solar(payload: dict, api_key: str) -> dict:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Reasoning consumes the same completion budget and can legitimately
        # take longer than a plain chat response. Keep this within the Job's
        # 600-second replica timeout while matching the independent reviewer.
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Response bodies can echo source content, so keep errors metadata-only.
        raise RuntimeError(f"Upstage API returned HTTP {exc.code}") from exc
    choice = body["choices"][0]
    content = choice["message"].get("content")
    if not content:
        finish_reason = choice.get("finish_reason", "unknown")
        raise RuntimeError(f"Upstage API returned no visible content (finish_reason={finish_reason})")
    content = content.strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(content)
    if set(result) != OUTPUT_FIELDS or not all(isinstance(result[key], str) and result[key].strip() for key in OUTPUT_FIELDS):
        raise ValueError("Solar response does not match the editorial draft contract")
    oversized = [key for key, limit in FIELD_CHAR_LIMITS.items() if len(result[key]) > limit]
    if oversized:
        raise ValueError(f"Solar response exceeds field limits: {', '.join(oversized)}")
    return result


def draft(packet: dict[str, str], model: str, api_key: str) -> dict:
    generated = call_solar(build_payload(packet, model), api_key)
    return {
        "source_name": packet["source_name"],
        "source_url": packet["source_url"],
        "published": packet["published"],
        "country": packet["country"],
        **generated,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "Solar 초안 · Codex 교차검토 및 사람 승인 필요",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_packet", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.getenv("UPSTAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--confirm-provider-terms", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(INBOX.resolve()) or output.suffix != ".json":
        print(f"--output must be a JSON file under {INBOX.relative_to(ROOT)}", file=sys.stderr)
        return 2
    if not args.confirm_provider_terms:
        print("--confirm-provider-terms is required before a billable provider call", file=sys.stderr)
        return 2
    api_key = resolve_api_key()
    if not api_key:
        print("UPSTAGE_API_KEY or UPSTAGE_KEY is required", file=sys.stderr)
        return 2
    packet = json.loads(args.source_packet.read_text(encoding="utf-8"))
    result = draft(packet, args.model, api_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
