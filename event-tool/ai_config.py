"""AI 숙의 구성 — 프로바이더 레지스트리 + 독파모 로스터.

런타임 편집(어드민 UI): roster.json 이 있으면 아래 기본값을 덮어쓴다.
- 프로바이더 = 엔드포인트/인증/기본 파라미터(키 자체는 .env, UI 노출 금지).
- 독파모 = 초안가 모델(provider × model).
가드(설계 G2): 초안가 독립 회사 ≥3, 판정기≠초안가. 하드코딩 fail-closed.
"""
import json
import os
from pathlib import Path

_ROSTER_FILE = Path(os.environ.get("EVENT_ROSTER_PATH", Path(__file__).parent / "roster.json"))

# ── 기본 프로바이더 레지스트리 (roster.json 없을 때 시드) ────────────────────
_DEFAULT_PROVIDERS = {
    "friendli": {
        "kind": "openai", "base": "https://api.friendli.ai/serverless/v1",
        "env": "FRIENDLI_AI_KEY", "max_tokens": 8000,
        "extra": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "upstage": {
        "kind": "openai", "base": "https://api.upstage.ai/v1",
        "env": "UPSTAGE_KEY", "max_tokens": 16000, "extra": {"reasoning_effort": "low"},
    },
    "sktax": {  # A.X (SKT) — 유효 키 확보 시 활성.
        "kind": "openai", "base": "https://api.sktax.chat/v1",
        "env": "ADOTX_API_KEY", "max_tokens": 4000, "enabled": False,
    },
    "clova": {  # HCX (Naver HyperCLOVA X) — CLOVA Studio v3. Bearer nv-키.
        "kind": "clova", "base": "https://clovastudio.stream.ntruss.com",
        "env": "CLOVA_STUDIO_TEST_KEY", "max_tokens": 4000,
    },
    "ollama": {  # 로컬 폴백
        "kind": "ollama", "base": "http://localhost:11434", "env": None, "max_tokens": 4000, "enabled": False,
    },
}

_DEFAULT_DOKPAMO = [
    {"label": "EXAONE", "company": "LG", "provider": "friendli", "model": "LGAI-EXAONE/K-EXAONE-236B-A23B"},
    {"label": "Solar", "company": "Upstage", "provider": "upstage", "model": "solar-pro3"},
    {"label": "HCX", "company": "Naver", "provider": "clova", "model": "HCX-005"},
    # {"label": "A.X", "company": "SKT", "provider": "sktax", "model": "ax4"},  # 유효 키 오면 UI에서 추가
]

MIN_DRAFTER_COMPANIES = 3  # fail-closed 하드코딩. 활성 독파모 <3이면 숙의 거부.

# ── 런타임 상태(roster.json 로드/기본값) ─────────────────────────────────────
PROVIDERS = {}
DOKPAMO = []


def _load():
    global PROVIDERS, DOKPAMO
    if _ROSTER_FILE.exists():
        try:
            d = json.loads(_ROSTER_FILE.read_text(encoding="utf-8"))
            PROVIDERS = d.get("providers") or dict(_DEFAULT_PROVIDERS)
            DOKPAMO = d.get("dokpamo") or list(_DEFAULT_DOKPAMO)
            return
        except Exception:
            pass
    PROVIDERS = {k: dict(v) for k, v in _DEFAULT_PROVIDERS.items()}
    DOKPAMO = [dict(x) for x in _DEFAULT_DOKPAMO]


def _persist():
    _ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ROSTER_FILE.write_text(json.dumps({"providers": PROVIDERS, "dokpamo": DOKPAMO},
                                       ensure_ascii=False, indent=2), encoding="utf-8")


_load()


def provider(name: str) -> dict:
    p = PROVIDERS.get(name)
    if not p:
        raise ValueError(f"알 수 없는 프로바이더: {name}")
    return p


def is_enabled(name: str) -> bool:
    p = PROVIDERS.get(name) or {}
    if p.get("enabled") is False:
        return False
    env = p.get("env")
    return (env is None) or bool(os.environ.get(env))  # 키 있으면 활성


def active_dokpamo() -> list[dict]:
    """키가 있어(enabled) 실제 호출 가능한 독파모만."""
    return [m for m in DOKPAMO if m.get("provider") in PROVIDERS and is_enabled(m["provider"])]


# ── 어드민 CRUD (키 값 자체는 절대 다루지 않음 — env 이름만) ──────────────────
def roster_view() -> dict:
    """어드민 표시용 — 프로바이더/독파모 + 각 활성(키 유무) 상태. 키 값은 노출 안 함."""
    provs = []
    for name, p in PROVIDERS.items():
        env = p.get("env")
        provs.append({"name": name, "kind": p.get("kind"), "base": p.get("base"),
                      "env": env, "max_tokens": p.get("max_tokens"),
                      "key_present": (env is None) or bool(os.environ.get(env)),
                      "disabled": p.get("enabled") is False})
    doks = [{**m, "enabled": is_enabled(m.get("provider", ""))} for m in DOKPAMO]
    return {"providers": provs, "dokpamo": doks,
            "min_companies": MIN_DRAFTER_COMPANIES,
            "active_companies": sorted({m["company"] for m in active_dokpamo()})}


def upsert_provider(name: str, *, kind: str, base: str, env: str | None,
                    max_tokens: int = 4000, extra: dict | None = None, disabled: bool = False):
    if not name.strip():
        raise ValueError("프로바이더 이름 필요")
    if kind not in ("openai", "clova", "ollama"):
        raise ValueError(f"지원 안 하는 kind: {kind} (openai/clova/ollama)")
    spec = {"kind": kind, "base": base.strip(), "env": (env or None), "max_tokens": int(max_tokens)}
    if extra:
        spec["extra"] = extra
    if disabled:
        spec["enabled"] = False
    PROVIDERS[name.strip()] = spec
    _persist()
    return roster_view()


def delete_provider(name: str):
    if any(m.get("provider") == name for m in DOKPAMO):
        raise ValueError(f"'{name}' 를 쓰는 독파모가 있어 삭제 불가(먼저 해당 독파모 삭제)")
    PROVIDERS.pop(name, None)
    _persist()
    return roster_view()


def add_dokpamo(*, label: str, company: str, provider: str, model: str):
    if not (label.strip() and company.strip() and model.strip()):
        raise ValueError("label·company·model 모두 필요")
    if provider not in PROVIDERS:
        raise ValueError(f"프로바이더 '{provider}' 먼저 등록하세요")
    if any(m["label"] == label.strip() for m in DOKPAMO):
        raise ValueError(f"이미 있는 독파모: {label}")
    DOKPAMO.append({"label": label.strip(), "company": company.strip(),
                    "provider": provider, "model": model.strip()})
    _persist()
    return roster_view()


def update_dokpamo(label: str, **fields):
    m = next((x for x in DOKPAMO if x["label"] == label), None)
    if not m:
        raise ValueError(f"없는 독파모: {label}")
    for k in ("company", "provider", "model"):
        if k in fields and fields[k]:
            if k == "provider" and fields[k] not in PROVIDERS:
                raise ValueError(f"프로바이더 '{fields[k]}' 없음")
            m[k] = fields[k].strip()
    _persist()
    return roster_view()


def delete_dokpamo(label: str):
    global DOKPAMO
    DOKPAMO = [x for x in DOKPAMO if x["label"] != label]
    _persist()
    return roster_view()


# ── 프롬프트(숙의 프로토콜 v2) ──────────────────────────────────────────────
_NO_NUMBER = ("정량 수치를 권위처럼 단정하지 말 것(예: '소득대체율 47.3%'). 방향·범위로만. 단일 정밀 숫자 금지.")
_DRIFT = "동시에 드리프트 감시: 시민 의견 이탈·환각·편향·누락이 보이면 반드시 지적하라."

DRAFTER_SYSTEM = ("너는 시민 의견을 빠짐없이 반영해 정책 추가 안을 설계하는 독립 전문가다. "
                  "반영/미반영/트레이드오프를 정직히 함께 낸다. " + _NO_NUMBER + " " + _DRIFT)
JSON_SPEC = ('JSON 객체로만: {"title","body","reflects"[반영],"tradeoffs"[감수],"unaddressed"[미반영, 비우지 말 것]}')
