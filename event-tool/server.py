"""정책 숙의 행사 도구 — 경량 백엔드 (FastAPI + SQLite). 설계=docs/event-tool-design.md.

개발 기본 스택은 FastAPI + SQLite(파일) + 빌드 없는 프론트다.
P0 시민 응답 화면 · P1 진행자 준비(행사/회차 생성·편집) + 인증.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
WEB = BASE / "web"
INSTANCES = BASE / "instances"


def _load_env():
    """event-tool/.env(gitignored) 있으면 로드 — 독파모 키(FRIENDLI_AI_KEY·UPSTAGE_KEY)."""
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
import ai_config as CFG  # noqa: E402
import db  # noqa: E402
import aipol_store  # noqa: E402
import aipol_admin_store  # noqa: E402
import aipol_chat  # noqa: E402
import aipol_batch  # noqa: E402
import aipol_receipt  # noqa: E402
import aipol_audit_checkpoint  # noqa: E402
import secret_env  # noqa: E402
import admin_auth  # noqa: E402
import sqlite_backup  # noqa: E402
from policy_lab.services.admin.rbac import Action, Principal, Role  # noqa: E402
from policy_lab.domains.pension.experiment import (  # noqa: E402
    CollectionDisabled,
    ExperimentError,
    IdempotencyConflict,
    ImmutableRecordConflict,
    InvalidTransition,
    StateRevisionConflict,
)

PRODUCTION = os.environ.get("EVENT_ENV", "development").lower() == "production"
DEMO_ENABLED = os.environ.get("EVENT_DEMO_ENABLED", "false" if PRODUCTION else "true").lower() == "true"
SESSION_SECRET = os.environ.get("EVENT_SESSION_SECRET", "local-development-session-secret")
SESSION_TTL = int(os.environ.get("EVENT_SESSION_TTL_SECONDS", "43200"))


def _admin_users() -> dict[str, str]:
    try:
        raw = secret_env.text("EVENT_ADMIN_USERS_JSON")
    except ValueError as exc:
        raise RuntimeError("EVENT_ADMIN_USERS_JSON_B64 형식 오류") from exc
    if raw:
        try:
            users = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("EVENT_ADMIN_USERS_JSON 형식 오류") from exc
        if not isinstance(users, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in users.items()):
            raise RuntimeError("EVENT_ADMIN_USERS_JSON은 사용자:비밀번호 객체여야 합니다")
        return users
    return {"local": os.environ.get("EVENT_ADMIN_PASSWORD", "demo")}


ADMIN_USERS = _admin_users()


def _admin_totp_secrets() -> dict[str, str]:
    try:
        raw = secret_env.text("EVENT_ADMIN_TOTP_SECRETS_JSON")
    except ValueError as exc:
        raise RuntimeError("EVENT_ADMIN_TOTP_SECRETS_JSON_B64 형식 오류") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not all(
            isinstance(username, str) and isinstance(value, str)
            for username, value in parsed.items()
        ):
            raise ValueError
        return {username: admin_auth.normalize_totp_secret(value)
                for username, value in parsed.items()}
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("EVENT_ADMIN_TOTP_SECRETS_JSON 형식 오류") from exc


ADMIN_TOTP_SECRETS = _admin_totp_secrets()


def _admin_totp_optional_users() -> frozenset[str]:
    raw = os.environ.get("EVENT_ADMIN_TOTP_OPTIONAL_USERS_JSON", "")
    if not raw:
        return frozenset()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or not all(
            isinstance(username, str) and username.strip() for username in parsed
        ):
            raise ValueError
        return frozenset(username.strip() for username in parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("EVENT_ADMIN_TOTP_OPTIONAL_USERS_JSON 형식 오류") from exc


ADMIN_TOTP_OPTIONAL_USERS = _admin_totp_optional_users()


def _admin_roles() -> dict[str, frozenset[Role]]:
    try:
        raw = secret_env.text("EVENT_ADMIN_ROLES_JSON")
    except ValueError as exc:
        raise RuntimeError("EVENT_ADMIN_ROLES_JSON_B64 형식 오류") from exc
    if not raw:
        # Generic event administration remains available, but AIPOL operations
        # require an explicit role map even in development.
        return {username: frozenset() for username in ADMIN_USERS}
    try:
        parsed = json.loads(raw)
        return {
            str(username): frozenset(Role(str(role)) for role in roles)
            for username, roles in parsed.items()
            if username in ADMIN_USERS and isinstance(roles, list)
        }
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise RuntimeError("EVENT_ADMIN_ROLES_JSON 형식 오류") from exc


ADMIN_ROLES = _admin_roles()
ADMIN_ROLES_CONFIGURED = bool(
    os.environ.get("EVENT_ADMIN_ROLES_JSON") or os.environ.get("EVENT_ADMIN_ROLES_JSON_B64")
)
LOGIN_FAILURES: dict[str, list[float]] = {}
if PRODUCTION:
    if len(SESSION_SECRET) < 32:
        raise RuntimeError("운영 환경 EVENT_SESSION_SECRET은 32자 이상이어야 합니다")
    if not ADMIN_USERS or any(not admin_auth.password_is_hashed(value) for value in ADMIN_USERS.values()):
        raise RuntimeError("운영 환경 관리자 비밀번호는 scrypt 해시로 저장해야 합니다")
    if not ADMIN_ROLES_CONFIGURED or set(ADMIN_USERS) != set(ADMIN_ROLES):
        raise RuntimeError("운영 환경 모든 진행자 계정에는 명시적 역할 매핑이 필요합니다")
    if not ADMIN_TOTP_OPTIONAL_USERS.issubset(ADMIN_USERS):
        raise RuntimeError("TOTP 생략 계정은 등록된 관리자여야 합니다")
    required_totp_users = set(ADMIN_USERS) - set(ADMIN_TOTP_OPTIONAL_USERS)
    if required_totp_users != set(ADMIN_TOTP_SECRETS):
        raise RuntimeError("운영 환경 TOTP 비밀값은 TOTP 생략 계정을 제외한 관리자 계정에 명시해야 합니다")

app = FastAPI(
    title="정책 숙의 행사 도구",
    docs_url=None if PRODUCTION else "/docs",
    redoc_url=None if PRODUCTION else "/redoc",
    openapi_url=None if PRODUCTION else "/openapi.json",
)
db.init()
db.fail_interrupted_jobs()
aipol_admin_store.init()
aipol_audit_checkpoint.configure(
    aipol_audit_checkpoint.store_from_environment(production=PRODUCTION)
)
if aipol_audit_checkpoint.configured():
    aipol_admin_store.reconcile_external_checkpoint(fail=True)
aipol_store.configure_completion_receipt_verifier(aipol_receipt.verifier_from_environment())
aipol_store.credential_readiness(fail=True)
aipol_admin_store.drain_experiment_audit_outbox()

AIPOL_CHATBOT_PUBLIC_ENABLED = os.environ.get("AIPOL_CHATBOT_PUBLIC_ENABLED", "false").lower() == "true"
AIPOL_CHAT_RATE_LIMIT = max(1, int(os.environ.get("AIPOL_CHAT_RATE_LIMIT_PER_MINUTE", "10")))
CHAT_RATE: dict[str, list[float]] = {}
CHAT_RATE_LOCK = threading.Lock()
AIPOL_REVIEW_EXCHANGE_RATE_LIMIT = min(
    100, max(1, int(os.environ.get("AIPOL_REVIEW_EXCHANGE_RATE_LIMIT_PER_MINUTE", "12")))
)
REVIEW_EXCHANGE_RATE: dict[str, list[float]] = {}
REVIEW_EXCHANGE_RATE_LOCK = threading.Lock()
AIPOL_REGISTRATION_FAILURE_WINDOW_SECONDS = min(
    3600, max(10, int(os.environ.get("AIPOL_REGISTRATION_FAILURE_WINDOW_SECONDS", "300")))
)
AIPOL_REGISTRATION_FAILURES_PER_REMOTE = min(
    100, max(1, int(os.environ.get("AIPOL_REGISTRATION_FAILURES_PER_REMOTE", "5")))
)
AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET = min(
    100_000, max(10, int(os.environ.get("AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET", "500")))
)
AIPOL_REGISTRATION_RATE_MAX_KEYS = min(
    100_000, max(100, int(os.environ.get("AIPOL_REGISTRATION_RATE_MAX_KEYS", "10000")))
)


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Load an explicit proxy allow-list; forwarded headers are off by default."""
    raw = os.environ.get("AIPOL_TRUSTED_PROXY_CIDRS", "").strip()
    if not raw:
        return ()
    try:
        return tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in raw.split(",")
            if value.strip()
        )
    except ValueError as exc:
        raise RuntimeError("AIPOL_TRUSTED_PROXY_CIDRS must contain valid IP CIDRs") from exc


TRUSTED_PROXY_NETWORKS = _trusted_proxy_networks()
REGISTRATION_FAILURES: dict[tuple[str, str], list[float]] = {}
REGISTRATION_GLOBAL_FAILURES: list[float] = []
REGISTRATION_RATE_LOCK = threading.Lock()
LOGIN_RATE_LOCK = threading.Lock()


def _auth_binding(username: str) -> str:
    material = f"{ADMIN_USERS[username]}|{ADMIN_TOTP_SECRETS.get(username, '')}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _token(username: str, *, mfa_verified_at: int | None = None) -> str:
    now = int(time.time())
    payload = json.dumps({
        "v": 3, "sub": username, "iat": now, "exp": now + SESSION_TTL,
        "mfa": mfa_verified_at, "auth": _auth_binding(username),
    }, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _token_claims(token: str) -> dict | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(SESSION_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)
        ).decode())
        if (
            payload.get("v") != 3 or payload.get("sub") not in ADMIN_USERS
            or not isinstance(payload.get("auth"), str)
            or not hmac.compare_digest(payload["auth"], _auth_binding(payload["sub"]))
            or not isinstance(payload.get("iat"), int) or not isinstance(payload.get("exp"), int)
            or payload["exp"] < int(time.time())
            or (payload.get("mfa") is not None and not isinstance(payload.get("mfa"), int))
        ):
            return None
        return payload
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None


def _token_user(token: str) -> str | None:
    claims = _token_claims(token)
    return str(claims["sub"]) if claims else None


def require_authenticated_admin(x_admin_token: str = Header(default="")) -> str:
    """서명·만료된 세션 토큰으로 개인 진행자 계정을 확인한다."""
    claims = _token_claims(x_admin_token)
    if not claims:
        raise HTTPException(401, "진행자 인증 실패")
    if PRODUCTION and claims.get("mfa") is None:
        raise HTTPException(401, "운영 관리자 2단계 인증이 필요합니다")
    return str(claims["sub"])


def require_admin(x_admin_token: str = Header(default="")) -> str:
    """기존 일반 관리자 API에는 admin 역할만 허용한다."""
    username = require_authenticated_admin(x_admin_token)
    if Role.ADMIN not in ADMIN_ROLES.get(username, frozenset()):
        raise HTTPException(403, "일반 관리자 권한이 필요합니다")
    return username


def require_aipol_admin(x_admin_token: str, action: Action) -> str:
    """서명 세션의 개인 계정과 명시적 역할을 작업에 결합한다."""
    username = require_authenticated_admin(x_admin_token)
    roles = ADMIN_ROLES.get(username, frozenset())
    try:
        Principal(username, roles).require(action)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403, str(exc)) from exc
    return username


_AIPOL_MUTATING_ACTIONS = frozenset({
    Action.EDIT_SOURCE,
    Action.EDIT_KNOWLEDGE,
    Action.SUBMIT_KNOWLEDGE,
    Action.APPROVE_KNOWLEDGE,
    Action.REVOKE_KNOWLEDGE,
    Action.RUN_BATCH,
    Action.CONFIGURE_CHATBOT,
    Action.MANAGE_ADMISSION,
    Action.MAINTAIN_SERVICE,
})


def require_aipol_mutation(x_admin_token: str, action: Action) -> str:
    """Single gate for every state-changing ``/api/admin/aipol`` route."""
    if action not in _AIPOL_MUTATING_ACTIONS:
        raise RuntimeError(f"AIPOL mutation route has no mutation role: {action.value}")
    actor = require_aipol_admin(x_admin_token, action)
    if aipol_audit_checkpoint.configured():
        try:
            aipol_admin_store.reconcile_external_checkpoint(fail=True)
        except aipol_audit_checkpoint.CheckpointError as exc:
            raise HTTPException(503, "audit checkpoint is not ready") from exc
    return actor


@app.middleware("http")
async def production_guards(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 65_536:
                return JSONResponse({"detail": "요청이 너무 큽니다"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Content-Length 형식이 올바르지 않습니다"}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
        "script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; form-action 'self'"
    )
    if (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/admin")
        or request.url.path == "/aipol-calculator-return.html"
        or request.url.path in {
            "/aipol-review.html", "/aipol-review.js", "/aipol-review.css",
        }
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    db.list_events()
    credential_status = aipol_store.credential_readiness()
    receipt_ready = aipol_store.completion_receipt_configured()
    admission_status = aipol_store.admission_readiness()
    checkpoint_status = aipol_admin_store.reconcile_external_checkpoint()
    payload = {
        "ready": True,
        "collection_ready": bool(
            credential_status["ready"] and receipt_ready and admission_status["ready"]
            and checkpoint_status["ready"]
        ),
        "credential_keys_ready": credential_status["ready"],
        "receipt_verifier": "configured" if receipt_ready else "disabled",
        "missing_credential_key_ids": credential_status["missing_key_ids"],
        "admission_inventory_ready": admission_status["ready"],
        "collection_closed_experiment_ids": admission_status["collection_closed_experiment_ids"],
        "legacy_admission_rotation_required_ids": admission_status[
            "legacy_admission_rotation_required_ids"
        ],
        "audit_checkpoint_ready": checkpoint_status["ready"],
        "audit_checkpoint_store": checkpoint_status["store"],
        "audit_checkpoint_sequence": checkpoint_status["sequence"],
        "backup_recovery_ready": not PRODUCTION,
    }
    if checkpoint_status["configured"] and not checkpoint_status["ready"]:
        return JSONResponse(payload, status_code=503)
    return payload


def _400(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))


def _validate_round_payload(body: dict) -> None:
    """공개 화면으로 전달되는 운영자 입력의 크기와 링크를 제한한다."""
    if len(str(body.get("title") or "")) > 200:
        raise HTTPException(400, "회차 제목은 200자 이하여야 합니다")
    for key, limit in (("intro", 20), ("attachments", 20), ("proposals", 20), ("profile_fields", 20)):
        value = body.get(key, [])
        if value is not None and (not isinstance(value, list) or len(value) > limit):
            raise HTTPException(400, f"{key} 형식 또는 개수가 올바르지 않습니다")
    for text in body.get("intro") or []:
        if len(str(text)) > 4_000:
            raise HTTPException(400, "안내 문단은 4,000자 이하여야 합니다")
    for proposal in body.get("proposals") or []:
        if not isinstance(proposal, dict) or not str(proposal.get("id") or "").strip():
            raise HTTPException(400, "각 정책안에는 ID가 필요합니다")
        if any(len(str(proposal.get(k) or "")) > n for k, n in (("id", 80), ("title", 300), ("body", 10_000))):
            raise HTTPException(400, "정책안 내용이 너무 깁니다")
    for attachment in body.get("attachments") or []:
        if not isinstance(attachment, dict):
            raise HTTPException(400, "첨부 자료 형식이 올바르지 않습니다")
        url = str(attachment.get("url") or "")
        parsed = urlparse(url)
        if url and not (url.startswith("/") or url == "#" or parsed.scheme == "https"):
            raise HTTPException(400, "첨부 링크는 HTTPS 또는 사이트 내부 경로만 허용합니다")


# ── 시민(공개) ────────────────────────────────────────────────────────────
@app.get("/api/citizen/current")
def citizen_current():
    """진행 중 설문. 운영 환경은 명시적으로 연 회차만 공개한다."""
    sv = db.active_survey()
    if sv:
        return {"open": True, "survey": sv}
    demo = BASE / "fixtures" / "demo.json"
    if DEMO_ENABLED and demo.exists():
        return {"open": True, "survey": json.loads(demo.read_text(encoding="utf-8")), "demo": True}
    return {"open": False}


def _check_contract(props: set[str], answers: dict) -> str | None:
    """계약: 모든 안 입장 필수 + 조건부는 의견 필수. 위반 시 메시지, 통과 시 None."""
    missing = [pid for pid in props if not (answers.get(pid) or {}).get("stance")]
    if missing:
        return f"모든 안에 응답해야 합니다(누락: {', '.join(missing)})"
    for pid in props:
        a = answers.get(pid) or {}
        if a.get("stance") == "conditional" and not (a.get("text") or "").strip():
            return f"{pid}: 조건부를 고르셨으면 조건을 적어주세요"
    return None


@app.post("/api/citizen/submit")
def citizen_submit(body: dict):
    """계약 재검증 후 실제 저장(DB 활성 회차) + 중복차단. 데모 폴백은 저장 안 함."""
    sv = db.active_survey()
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        raise HTTPException(400, "응답 형식이 올바르지 않습니다")
    if not sv and not DEMO_ENABLED:
        raise HTTPException(409, "진행 중인 설문이 없습니다")
    source = sv or json.loads((BASE / "fixtures" / "demo.json").read_text(encoding="utf-8"))
    props = {p["id"] for p in source["proposals"]}
    if set(answers) - props:
        raise HTTPException(400, "설문에 없는 안이 포함되어 있습니다")
    for answer in answers.values():
        if not isinstance(answer, dict) or answer.get("stance") not in (None, "accept", "conditional", "reject"):
            raise HTTPException(400, "입장 값이 올바르지 않습니다")
        if len(str(answer.get("text") or "")) > 2_000:
            raise HTTPException(400, "의견은 2,000자 이하여야 합니다")
    profile = body.get("profile") or {}
    if not isinstance(profile, dict) or len(profile) > 20 or any(len(str(v)) > 200 for v in profile.values()):
        raise HTTPException(400, "참여자 정보가 너무 큽니다")
    err = _check_contract(props, answers)
    if err:
        return {"ok": False, "error": err}
    if not sv:  # 진행 중 DB 회차 없음(데모) → 저장 안 함
        return {"ok": True, "code": "DEMO", "note": "데모 설문 — 진행 중 회차가 아니라 저장하지 않았습니다"}
    try:
        out = db.save_response(sv["round_id"], body.get("code") or None, profile,
                               answers, segment_key=sv.get("segment_key", ""))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "code": out["code"], "note": "응답이 저장되었습니다"}


# ── 진행자(어드민) ────────────────────────────────────────────────────────
@app.post("/api/admin/login")
def admin_login(body: dict, request: Request):
    client = _remote_address(request)
    username = str(body.get("username", ""))
    failure_identity = username.casefold()[:128] if username in ADMIN_USERS else "<unknown>"
    failure_key = f"{client}|{failure_identity}"
    now = time.time()
    with LOGIN_RATE_LOCK:
        recent = [ts for ts in LOGIN_FAILURES.get(failure_key, []) if now - ts < 900]
        if len(recent) >= 10:
            raise HTTPException(429, "too many login attempts; try again later")
    expected = ADMIN_USERS.get(username)
    password = str(body.get("password", ""))
    otp = str(body.get("otp", "")).strip()
    password_valid = expected is not None and admin_auth.verify_password(
        password, expected, allow_plaintext=not PRODUCTION
    )
    totp_secret = ADMIN_TOTP_SECRETS.get(username)
    totp_optional = username in ADMIN_TOTP_OPTIONAL_USERS
    otp_counter = (
        admin_auth.matching_totp_counter(totp_secret, otp, at_epoch=int(now))
        if PRODUCTION and totp_secret is not None else None
    )
    otp_valid = not PRODUCTION or totp_optional or otp_counter is not None
    replayed_otp = False
    if PRODUCTION and password_valid and otp_counter is not None:
        with LOGIN_RATE_LOCK:
            replayed_otp = not db.claim_totp_counter(username, otp_counter)
    if not password_valid or not otp_valid or replayed_otp:
        with LOGIN_RATE_LOCK:
            # Re-read while holding the lock: concurrent failures may have
            # arrived after the initial admission check.
            recent = [ts for ts in LOGIN_FAILURES.get(failure_key, []) if now - ts < 900]
            if len(recent) >= 10:
                raise HTTPException(429, "로그인 시도가 너무 많습니다. 잠시 뒤 다시 시도해 주세요")
            LOGIN_FAILURES[failure_key] = recent + [now]
        raise HTTPException(401, "아이디, 비밀번호 또는 인증 코드가 틀렸습니다")
    with LOGIN_RATE_LOCK:
        LOGIN_FAILURES.pop(failure_key, None)
    return {
        "ok": True,
        "token": _token(
            username,
            mfa_verified_at=int(now)
            if otp_valid and (totp_secret is not None or totp_optional)
            else None,
        ),
        "username": username,
        "roles": sorted(role.value for role in ADMIN_ROLES.get(username, ())),
        "expires_in": SESSION_TTL,
    }


@app.get("/api/admin/events")
def admin_events(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    out = []
    for ev in db.list_events():
        ev["rounds"] = db.list_rounds(ev["id"])
        out.append(ev)
    return out


@app.post("/api/admin/events")
def admin_create_event(body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    if len(str(body.get("title") or "")) > 200 or len(str(body.get("context") or "")) > 10_000:
        raise HTTPException(400, "행사 제목 또는 맥락이 너무 깁니다")
    return _400(db.create_event, body.get("title", ""), body.get("context", ""))


@app.post("/api/admin/events/{eid}/rounds")
def admin_create_round(eid: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    _validate_round_payload(body)
    return _400(db.create_round, eid, round_no=int(body.get("round_no", 1)),
                title=body.get("title", ""), intro=body.get("intro", []),
                attachments=body.get("attachments", []), proposals=body.get("proposals", []),
                profile_fields=body.get("profile_fields", []))


@app.patch("/api/admin/rounds/{rid}")
def admin_update_round(rid: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    _validate_round_payload(body)
    return _400(db.update_round, rid, **body)


@app.post("/api/admin/rounds/{rid}/status")
def admin_round_status(rid: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    r = db.get_round(rid)
    if not r:
        raise HTTPException(404, "회차 없음")
    st = body.get("status")
    if st not in ("draft", "open", "closed"):
        raise HTTPException(400, "상태는 draft|open|closed")
    db.update_round(rid, status=st)
    if st == "open":  # 열면 진행 중으로
        db.set_active_round(r["event_id"], rid)
    return db.get_round(rid)


@app.get("/api/admin/rounds/{rid}/stats")
def admin_round_stats(rid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(db.round_stats, rid)


# ── AI 숙의 (P3): 서버측 잡 ───────────────────────────────────────────────
import deliberate as DELIB  # noqa: E402


@app.post("/api/admin/rounds/{rid}/deliberate")
def admin_deliberate(rid: str, bg: BackgroundTasks, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    rd = db.get_round(rid)
    if not rd:
        raise HTTPException(404, "회차 없음")
    if db.round_stats(rid)["n"] == 0:
        raise HTTPException(400, "응답이 없어 숙의할 수 없습니다")
    job = db.create_job(rid)
    bg.add_task(DELIB.run_job, job["id"], rid)  # 서버측 비동기(브라우저 안 묶임)
    return job


@app.get("/api/admin/jobs/{jid}")
def admin_job(jid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    j = db.get_job(jid)
    if not j:
        raise HTTPException(404, "잡 없음")
    if j["status"] == "done":
        dls = db.deliberations_for_round(j["round_id"])
        j["result"] = dls[0] if dls else None
    return j


@app.post("/api/admin/jobs/{jid}/cancel")
def admin_job_cancel(jid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    db.update_job(jid, cancel=1)
    return {"ok": True}


@app.get("/api/admin/rounds/{rid}/deliberations")
def admin_deliberations(rid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return db.deliberations_for_round(rid)


# ── AI안 사람수정 · 승인 (P4, human_gate) ──────────────────────────────────
@app.post("/api/admin/deliberations/{did}/revise")
def admin_revise(did: str, body: dict, x_admin_token: str = Header(default="")):
    username = require_admin(x_admin_token)
    return _400(db.revise_deliberation, did, editor=username,
                title=body.get("title", ""), body=body.get("body", ""), reason=body.get("reason", ""),
                source=body.get("source", "개인수정"), meeting=body.get("meeting"))


@app.post("/api/admin/deliberations/{did}/approve")
def admin_approve(did: str, x_admin_token: str = Header(default="")):
    username = require_admin(x_admin_token)
    return _400(db.approve_deliberation, did, username)


@app.post("/api/admin/deliberations/{did}/to_next_round")
def admin_to_next(did: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(db.to_next_round, did, int(body.get("next_round_no", 2)))


# ── AI 에이전트(독파모/프로바이더) 관리 — 키 값은 다루지 않음(env 이름만) ──
@app.get("/api/admin/agents")
def admin_agents(x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return CFG.roster_view()


@app.post("/api/admin/agents/dokpamo")
def admin_add_dokpamo(body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(CFG.add_dokpamo, label=body.get("label", ""), company=body.get("company", ""),
                provider=body.get("provider", ""), model=body.get("model", ""))


@app.patch("/api/admin/agents/dokpamo/{label}")
def admin_update_dokpamo(label: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(CFG.update_dokpamo, label, **{k: body[k] for k in ("company", "provider", "model") if k in body})


@app.delete("/api/admin/agents/dokpamo/{label}")
def admin_delete_dokpamo(label: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(CFG.delete_dokpamo, label)


@app.post("/api/admin/agents/providers")
def admin_upsert_provider(body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(CFG.upsert_provider, body.get("name", ""), kind=body.get("kind", "openai"),
                base=body.get("base", ""), env=body.get("env"), max_tokens=body.get("max_tokens", 4000),
                extra=body.get("extra"), disabled=bool(body.get("disabled", False)))


@app.delete("/api/admin/agents/providers/{name}")
def admin_delete_provider(name: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(CFG.delete_provider, name)


# ── 삭제 (운영자 되돌리기·정리) ───────────────────────────────────────────
@app.patch("/api/admin/events/{eid}")
def admin_update_event(eid: str, body: dict, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(db.update_event, eid, title=body.get("title"), context=body.get("context"))


@app.delete("/api/admin/events/{eid}")
def admin_delete_event(eid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    db.delete_event(eid)
    return {"ok": True}


@app.delete("/api/admin/rounds/{rid}")
def admin_delete_round(rid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    db.delete_round(rid)
    return {"ok": True}


# ── 개개인 응답자 열람 (개인정보=AI 페르소나) ─────────────────────────────
@app.get("/api/admin/events/{eid}/participants")
def admin_participants(eid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return db.list_participants(eid)


@app.get("/api/admin/participants/{pid}")
def admin_participant_detail(pid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    d = db.participant_detail(pid)
    if not d:
        raise HTTPException(404, "참여자 없음")
    return d


# ── 최종 보고서 (P6) ───────────────────────────────────────────────────────
@app.get("/api/admin/events/{eid}/report")
def admin_report(eid: str, x_admin_token: str = Header(default="")):
    require_admin(x_admin_token)
    return _400(db.final_report, eid)


# ── AIPOL 연금 3차 측정 (기존 2회차 일반 설문과 저장 경계 분리) ───────────
def _aipol_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except aipol_store.ParticipantAuthenticationError as exc:
        raise HTTPException(401, str(exc)) from exc
    except CollectionDisabled as exc:
        raise HTTPException(423, str(exc)) from exc
    except (IdempotencyConflict, ImmutableRecordConflict, InvalidTransition,
            StateRevisionConflict, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ExperimentError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _require_exact_contract(body: dict, required: set[str], optional: set[str], label: str) -> None:
    keys = set(body)
    missing = required - keys
    unexpected = keys - required - optional
    if missing or unexpected:
        raise HTTPException(
            400,
            f"{label} 계약 필드 오류 (missing={sorted(missing)}, unexpected={sorted(unexpected)})",
        )


def _audit_experiment_mutation(actor: str, action: str, experiment_id: str, result):
    # The mutation already persisted a durable outbox row in its own SQLite
    # transaction. Delivery is best-effort here and retried on process startup.
    try:
        aipol_admin_store.drain_experiment_audit_outbox()
    except sqlite3.Error:
        pass
    return result


def _expected_revision(body: dict) -> int:
    value = body.get("expected_revision")
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, "expected_revision은 정수여야 합니다")
    return value


@app.get("/api/admin/aipol/experiments")
def aipol_admin_experiments(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_store.list_experiments()


@app.post("/api/admin/aipol/experiments")
def aipol_admin_create(body: dict, x_admin_token: str = Header(default="")):
    created_by = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    _require_exact_contract(
        body,
        {
            "title", "experiment_version", "session_id", "consent_version",
            "consent_text", "question_id", "question_text", "option_set_version",
            "policy_options", "capacity",
        },
        {"procedure_version"},
        "experiment creation",
    )
    result = _aipol_call(
        aipol_store.create_experiment,
        title=str(body.get("title") or ""),
        experiment_version=str(body.get("experiment_version") or ""),
        session_id=str(body.get("session_id") or ""),
        consent_version=str(body.get("consent_version") or ""),
        consent_text=str(body.get("consent_text") or ""),
        question_id=str(body.get("question_id") or ""),
        question_text=str(body.get("question_text") or ""),
        option_set_version=str(body.get("option_set_version") or ""),
        policy_options=body.get("policy_options") or [],
        capacity=body.get("capacity"),
        created_by=created_by,
        procedure_version=str(body.get("procedure_version") or "v1"),
    )
    return _audit_experiment_mutation(created_by, "experiment.created", result["id"], result)


@app.post("/api/admin/aipol/experiments/{experiment_id}/admission-seats/rotate")
def aipol_admin_rotate_legacy_admission_seats(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    actor = require_aipol_mutation(x_admin_token, Action.MANAGE_ADMISSION)
    _require_exact_contract(
        body, {"reason", "new_capacity", "confirmation"}, set(),
        "admission seat rotation",
    )
    reason = body.get("reason")
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        raise HTTPException(400, "rotation reason must be 8 to 500 characters")
    new_capacity = body.get("new_capacity")
    if isinstance(new_capacity, bool) or not isinstance(new_capacity, int):
        raise HTTPException(400, "new_capacity must be an integer")
    confirmation = body.get("confirmation")
    if not isinstance(confirmation, str):
        raise HTTPException(400, "rotation confirmation must be a string")
    result = _aipol_call(
        aipol_store.rotate_legacy_admission_seats,
        experiment_id,
        actor=actor,
        reason=reason.strip(),
        new_capacity=new_capacity,
        confirmation=confirmation,
    )
    return _audit_experiment_mutation(
        actor, "experiment.admission_seats.rotated", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/review-seat-sets")
def aipol_admin_issue_review_seat_set(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    actor = require_aipol_mutation(x_admin_token, Action.MANAGE_ADMISSION)
    _require_exact_contract(
        body, {"logical_seat_ids", "expires_in_seconds", "idempotency_key"}, set(),
        "professor review seat set",
    )
    result = _aipol_call(
        aipol_store.issue_review_seat_set,
        experiment_id,
        logical_seat_ids=body.get("logical_seat_ids"),
        expires_in_seconds=body.get("expires_in_seconds"),
        idempotency_key=body.get("idempotency_key"),
        issued_by=actor,
    )
    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/review-seat-sets/{review_id}/revoke")
def aipol_admin_revoke_review_seat(
    experiment_id: str, review_id: str, body: dict,
    x_admin_token: str = Header(default=""),
):
    actor = require_aipol_mutation(x_admin_token, Action.MANAGE_ADMISSION)
    _require_exact_contract(body, {"logical_seat_id", "reason"}, set(), "review seat revoke")
    result = _aipol_call(
        aipol_store.revoke_review_seat,
        experiment_id,
        review_id,
        logical_seat_id=body.get("logical_seat_id"),
        reason=body.get("reason"),
        revoked_by=actor,
    )
    return _audit_experiment_mutation(
        actor, "experiment.review_seat.revoked", experiment_id, result
    )


@app.put("/api/admin/aipol/experiments/{experiment_id}/freeze")
def aipol_admin_freeze(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    approved_by = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    _require_exact_contract(
        body,
        {
            "manifest_id", "experiment_version", "option_set_version",
            "measurement_spec_hash", "status", "collection_enabled", "approvals",
        },
        set(),
        "freeze manifest",
    )
    if (
        not isinstance(body.get("collection_enabled"), bool)
        or not isinstance(body.get("approvals"), list)
        or not all(isinstance(body.get(key), str) for key in (
            "manifest_id", "experiment_version", "option_set_version",
            "measurement_spec_hash", "status",
        ))
    ):
        raise HTTPException(400, "freeze manifest field types do not match the contract")
    result = _aipol_call(
        aipol_store.set_freeze_manifest, experiment_id, body, approved_by=approved_by
    )
    return _audit_experiment_mutation(approved_by, "experiment.frozen", experiment_id, result)


@app.post("/api/admin/aipol/experiments/{experiment_id}/canonical-documents/preview")
def aipol_admin_canonical_preview(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(
        aipol_store.canonical_document_hash_preview,
        experiment_id,
        category=str(body.get("category") or ""),
        document_id=str(body.get("document_id") or ""),
        document_version=str(body.get("document_version") or ""),
        body=str(body.get("body") or ""),
        evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/canonical-documents")
def aipol_admin_canonical_document(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    registered_by = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    result = _aipol_call(
        aipol_store.register_canonical_document,
        experiment_id,
        category=str(body.get("category") or ""),
        document_id=str(body.get("document_id") or ""),
        document_version=str(body.get("document_version") or ""),
        body=str(body.get("body") or ""),
        evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
        declared_content_hash=str(body.get("declared_content_hash") or ""),
        approval_id=str(body.get("approval_id") or ""),
        approved_by=str(body.get("approved_by") or ""),
        registered_by=registered_by,
    )
    return _audit_experiment_mutation(
        registered_by, "experiment.canonical.approved", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/canonical-drafts")
def aipol_admin_canonical_draft(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    editor_by = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    _require_exact_contract(
        body,
        {
            "category", "document_id", "document_version", "body", "evidence",
            "declared_content_hash",
        },
        set(),
        "canonical draft",
    )
    result = _aipol_call(
        aipol_store.register_canonical_draft,
        experiment_id,
        category=str(body.get("category") or ""),
        document_id=str(body.get("document_id") or ""),
        document_version=str(body.get("document_version") or ""),
        body=str(body.get("body") or ""),
        evidence=body.get("evidence") if isinstance(body.get("evidence"), dict) else {},
        declared_content_hash=str(body.get("declared_content_hash") or ""),
        editor_by=editor_by,
    )
    return _audit_experiment_mutation(
        editor_by, "experiment.canonical.drafted", experiment_id, result
    )


@app.get("/api/admin/aipol/experiments/{experiment_id}/canonical-drafts")
def aipol_admin_canonical_drafts(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(aipol_store.list_canonical_drafts, experiment_id)


@app.get("/api/admin/aipol/experiments/{experiment_id}/canonical-documents")
def aipol_admin_canonical_documents(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(aipol_store.list_canonical_documents, experiment_id)


@app.post("/api/admin/aipol/experiments/{experiment_id}/artifacts")
def aipol_admin_artifact(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    registered_by = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    if not isinstance(body.get("content"), dict):
        raise HTTPException(400, "content는 JSON 객체여야 합니다")
    if not isinstance(body.get("fallback_used", False), bool):
        raise HTTPException(400, "fallback_used는 boolean이어야 합니다")
    result = _aipol_call(
        aipol_store.set_artifact,
        experiment_id,
        kind=str(body.get("kind") or ""),
        artifact_id=str(body.get("artifact_id") or ""),
        artifact_version=str(body.get("artifact_version") or ""),
        content=body.get("content") or {},
        approval_id=str(body.get("approval_id") or ""),
        approved_by=str(body.get("approved_by") or ""),
        registered_by=registered_by,
        fallback_used=bool(body.get("fallback_used", False)),
    )
    return _audit_experiment_mutation(
        registered_by, "experiment.artifact.approved", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/ai-candidates")
def aipol_admin_ai_candidate(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    registered_by = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    _require_exact_contract(
        body,
        {
            "candidate_role", "artifact_id", "artifact_version", "content", "model",
            "deployment", "prompt_version", "generated_at", "evidence_refs", "approval_id",
            "approved_by",
        },
        {"m2_aggregate_hash"},
        "AI candidate",
    )
    string_fields = (
        "candidate_role", "artifact_id", "artifact_version", "model", "deployment",
        "prompt_version", "generated_at", "approval_id", "approved_by",
    )
    if not all(isinstance(body.get(key), str) for key in string_fields):
        raise HTTPException(400, "AI candidate provenance fields must be strings")
    if not isinstance(body.get("content"), dict) or not isinstance(body.get("evidence_refs"), list):
        raise HTTPException(400, "AI content는 객체, evidence_refs는 배열이어야 합니다")
    result = _aipol_call(
        aipol_store.set_ai_candidate,
        experiment_id,
        candidate_role=str(body.get("candidate_role") or ""),
        artifact_id=str(body.get("artifact_id") or ""),
        artifact_version=str(body.get("artifact_version") or ""),
        content=body["content"],
        model=str(body.get("model") or ""),
        deployment=str(body.get("deployment") or ""),
        prompt_version=str(body.get("prompt_version") or ""),
        generated_at=str(body.get("generated_at") or ""),
        evidence_refs=body["evidence_refs"],
        m2_aggregate_hash=body.get("m2_aggregate_hash"),
        approval_id=str(body.get("approval_id") or ""),
        approved_by=str(body.get("approved_by") or ""),
        registered_by=registered_by,
    )
    return _audit_experiment_mutation(
        registered_by, "experiment.ai_candidate.approved", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/close-registration")
def aipol_admin_close_registration(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    result = _aipol_call(aipol_store.close_registration, experiment_id, actor=actor)
    return _audit_experiment_mutation(actor, "experiment.registration.closed", experiment_id, result)


@app.post("/api/admin/aipol/experiments/{experiment_id}/public-results/{result_stage}/release")
def aipol_admin_release_public_result(
    experiment_id: str,
    result_stage: str,
    body: dict,
    x_admin_token: str = Header(default=""),
):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    _require_exact_contract(
        body, {"cutoff_at", "rules_version"}, set(), "public result release"
    )
    result = _aipol_call(
        aipol_store.release_public_result,
        experiment_id,
        result_stage,
        cutoff_at=str(body.get("cutoff_at") or ""),
        rules_version=str(body.get("rules_version") or ""),
        released_by=actor,
    )
    return _audit_experiment_mutation(
        actor, f"experiment.public_result.{result_stage.lower()}.released", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/release-e2")
def aipol_admin_release_e2(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    selected_by = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    result = _aipol_call(
        aipol_store.release_e2,
        experiment_id,
        candidate_role=str(body.get("candidate_role") or ""),
        selection_reason=str(body.get("selection_reason") or ""),
        selected_by=selected_by,
    )
    return _audit_experiment_mutation(selected_by, "experiment.e2.released", experiment_id, result)


@app.get("/api/admin/aipol/experiments/{experiment_id}/m2-aggregate")
def aipol_admin_m2_aggregate(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(aipol_store.m2_aggregate_snapshot, experiment_id)


@app.get("/api/admin/aipol/experiments/{experiment_id}/m2-reason-classification-pending")
def aipol_admin_m2_reason_classification_pending(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    classifier = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    return _aipol_call(
        aipol_store.list_pending_m2_reason_classifications,
        experiment_id, classifier=classifier,
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/m2-reason-classification-drafts")
def aipol_admin_m2_reason_classification_draft(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    classified_by = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    _require_exact_contract(
        body,
        {"participant_pseudonym", "option_id", "reason_hash", "topic_codes"},
        set(),
        "M2 reason classification draft",
    )
    if not isinstance(body.get("topic_codes"), list):
        raise HTTPException(400, "topic_codes는 사전 승인 코드 배열이어야 합니다")
    result = _aipol_call(
        aipol_store.register_m2_reason_classification_draft,
        experiment_id,
        participant_pseudonym=str(body.get("participant_pseudonym") or ""),
        option_id=str(body.get("option_id") or ""),
        reason_hash=str(body.get("reason_hash") or ""),
        topic_codes=body["topic_codes"],
        classified_by=classified_by,
    )
    return _audit_experiment_mutation(
        classified_by, "experiment.m2_reason_classification.drafted", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/m2-reason-classifications")
def aipol_admin_m2_reason_classification(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    approved_by = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    _require_exact_contract(
        body, {"draft_id", "draft_hash", "approval_id"}, set(),
        "M2 reason classification approval",
    )
    result = _aipol_call(
        aipol_store.approve_m2_reason_classification,
        experiment_id,
        draft_id=str(body.get("draft_id") or ""),
        draft_hash=str(body.get("draft_hash") or ""),
        approval_id=str(body.get("approval_id") or ""),
        approved_by=approved_by,
    )
    return _audit_experiment_mutation(
        approved_by, "experiment.m2_reason_classification.approved", experiment_id, result
    )


@app.get("/api/admin/aipol/experiments/{experiment_id}/public-audience-inputs")
def aipol_admin_public_audience_inputs(
    experiment_id: str, x_admin_token: str = Header(default="")
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(aipol_store.public_audience_input_snapshot, experiment_id)


@app.post("/api/admin/aipol/experiments/{experiment_id}/public-audience-inputs")
def aipol_admin_register_public_audience_input(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    selected_by = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    _require_exact_contract(
        body,
        {"sequence", "statement", "idempotency_key"},
        set(),
        "public audience input",
    )
    result = _aipol_call(
        aipol_store.register_public_audience_input,
        experiment_id,
        sequence=body.get("sequence"),
        statement=body.get("statement"),
        selected_by=selected_by,
        idempotency_key=str(body.get("idempotency_key") or ""),
    )
    return _audit_experiment_mutation(
        selected_by, "experiment.public_audience_input.selected", experiment_id, result
    )


@app.post("/api/admin/aipol/experiments/{experiment_id}/mark-pending-attrition")
def aipol_admin_mark_pending_attrition(
    experiment_id: str, body: dict, x_admin_token: str = Header(default="")
):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    result = _aipol_call(
        aipol_store.mark_pending_attrition,
        experiment_id,
        actor=actor,
        reason=str(body.get("reason") or ""),
    )
    return _audit_experiment_mutation(actor, "experiment.attrition.marked", experiment_id, result)


@app.post("/api/admin/aipol/experiments/{experiment_id}/synthetic-participants")
def aipol_admin_synthetic(experiment_id: str, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    result = _aipol_call(
        aipol_store.register_participant, experiment_id, "synthetic", audit_actor=actor
    )
    return _audit_experiment_mutation(actor, "experiment.synthetic.registered", experiment_id, result)


@app.post(
    "/api/admin/aipol/experiments/{experiment_id}/synthetic-participants/{review_id}/revoke"
)
def aipol_admin_revoke_synthetic_review(
    experiment_id: str,
    review_id: str,
    body: dict,
    x_admin_token: str = Header(default=""),
):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    _require_exact_contract(body, {"reason"}, set(), "synthetic review revocation")
    result = _aipol_call(
        aipol_store.revoke_synthetic_review,
        experiment_id,
        review_id,
        actor=actor,
        reason=str(body.get("reason") or ""),
    )
    return _audit_experiment_mutation(
        actor, "experiment.synthetic_review.revoked", experiment_id, result
    )


@app.get("/api/admin/aipol/experiments/{experiment_id}/summary")
def aipol_admin_summary(
    experiment_id: str,
    participant_type: str = "real",
    x_admin_token: str = Header(default=""),
):
    require_aipol_admin(x_admin_token, Action.READ)
    return _aipol_call(aipol_store.admin_summary, experiment_id, participant_type)


# ── AIPOL 통합 관리자: 출처 · 지식 · 배치 · 챗봇 ─────────────────────────
def _admin_store_call(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if aipol_audit_checkpoint.configured():
            aipol_admin_store.reconcile_external_checkpoint(fail=True)
        return result
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except aipol_audit_checkpoint.CheckpointError as exc:
        raise HTTPException(503, "audit checkpoint is not ready") from exc


@app.get("/api/admin/aipol/sources")
def aipol_admin_sources(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_admin_store.list_sources()


@app.post("/api/admin/aipol/sources")
def aipol_admin_save_source(body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.EDIT_SOURCE)
    return _admin_store_call(aipol_admin_store.save_source, body, actor)


@app.get("/api/admin/aipol/knowledge")
def aipol_admin_knowledge(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_admin_store.list_knowledge()


@app.post("/api/admin/aipol/knowledge")
def aipol_admin_create_knowledge(body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    return _admin_store_call(aipol_admin_store.create_knowledge, body, actor)


@app.post("/api/admin/aipol/knowledge/{knowledge_id}/revisions")
def aipol_admin_revise_knowledge(knowledge_id: str, body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    return _admin_store_call(
        aipol_admin_store.revise_knowledge,
        knowledge_id,
        body,
        actor,
        body.get("expected_revision"),
    )


@app.post("/api/admin/aipol/knowledge/{knowledge_id}/submit")
def aipol_admin_submit_knowledge(knowledge_id: str, body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.SUBMIT_KNOWLEDGE)
    return _admin_store_call(
        aipol_admin_store.transition_knowledge, knowledge_id, "in_review", actor,
        str(body.get("reason") or ""), body.get("expected_revision"),
    )


@app.post("/api/admin/aipol/knowledge/{knowledge_id}/approve")
def aipol_admin_approve_knowledge(knowledge_id: str, body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.APPROVE_KNOWLEDGE)
    return _admin_store_call(
        aipol_admin_store.transition_knowledge, knowledge_id, "approved", actor,
        str(body.get("reason") or ""), body.get("expected_revision"),
    )


@app.post("/api/admin/aipol/knowledge/{knowledge_id}/revoke")
def aipol_admin_revoke_knowledge(knowledge_id: str, body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.REVOKE_KNOWLEDGE)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "철회 사유가 필요합니다")
    return _admin_store_call(
        aipol_admin_store.transition_knowledge,
        knowledge_id,
        "revoked",
        actor,
        reason,
        body.get("expected_revision"),
    )


@app.post("/api/admin/aipol/knowledge/import")
def aipol_admin_import_knowledge(body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.EDIT_KNOWLEDGE)
    return _admin_store_call(aipol_admin_store.import_human_approved, body, actor)


@app.get("/api/admin/aipol/batch-configs")
def aipol_admin_batch_configs(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_admin_store.list_batch_configs()


@app.put("/api/admin/aipol/batch-configs/{config_id}")
def aipol_admin_save_batch_config(config_id: str, body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    return _admin_store_call(aipol_admin_store.save_batch_config, {**body, "id": config_id}, actor)


@app.get("/api/admin/aipol/batch-runs")
def aipol_admin_batch_runs(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_admin_store.list_batch_runs()


@app.post("/api/admin/aipol/batch-configs/{config_id}/request")
def aipol_admin_request_batch(config_id: str, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.RUN_BATCH)
    run = _admin_store_call(aipol_admin_store.request_batch, config_id, actor)
    runner = aipol_batch.runner_from_environment()
    try:
        execution = runner.start()
    except aipol_batch.BatchDispatchError as exc:
        aipol_admin_store.mark_batch_dispatch_failed(run["id"], exc.code, actor)
        raise HTTPException(503, str(exc)) from exc
    return aipol_admin_store.mark_batch_started(
        run["id"], runner.job_resource_id, execution.name, execution.status, actor
    )


@app.get("/api/admin/aipol/batch-runs/{run_id}/status")
def aipol_admin_batch_status(run_id: str, x_admin_token: str = Header(default="")):
    actor = require_aipol_admin(x_admin_token, Action.READ)
    run = _admin_store_call(aipol_admin_store.get_batch_run, run_id)
    execution_name = run.get("azure_execution_name")
    if not execution_name or run["status"] in {"succeeded", "failed", "stopped"}:
        return run
    runner = aipol_batch.runner_from_environment()
    if runner.job_resource_id != run.get("azure_job_resource_id"):
        raise HTTPException(503, "현재 Azure Job resource ID가 실행 기록과 다릅니다")
    try:
        execution = runner.status(execution_name)
    except aipol_batch.BatchDispatchError as exc:
        raise HTTPException(503, str(exc)) from exc
    return aipol_admin_store.update_batch_remote_status(
        run_id, execution.status, execution.started_at, execution.finished_at, actor
    )


@app.get("/api/admin/aipol/chatbot-config")
def aipol_admin_chatbot_config(x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ)
    return aipol_admin_store.get_chatbot_config()


@app.put("/api/admin/aipol/chatbot-config")
def aipol_admin_save_chatbot_config(body: dict, x_admin_token: str = Header(default="")):
    actor = require_aipol_mutation(x_admin_token, Action.CONFIGURE_CHATBOT)
    return _admin_store_call(aipol_admin_store.save_chatbot_config, body, actor)


@app.get("/api/admin/aipol/audit")
def aipol_admin_audit(limit: int = 200, x_admin_token: str = Header(default="")):
    require_aipol_admin(x_admin_token, Action.READ_AUDIT)
    return {"valid": aipol_admin_store.verify_audit_chain(), "events": aipol_admin_store.list_audit(limit)}


@app.post("/api/admin/aipol/maintenance/backup")
def aipol_admin_backup(x_admin_token: str = Header(default="")):
    """직렬 HTTP 경계 안에서 수집 중단을 확인하고 검증 백업을 만든다."""
    actor = require_aipol_mutation(x_admin_token, Action.MAINTAIN_SERVICE)
    if PRODUCTION:
        raise HTTPException(
            503,
            "운영 백업은 불변 감사 체크포인트 복구 계보가 준비될 때까지 비활성화되어 있습니다",
        )
    aipol_admin_store.append_external_audit(
        actor=actor, action="database.backup.requested", resource_type="database",
        resource_id="event.db", payload={},
    )
    try:
        result = sqlite_backup.create_verified_backup()
    except sqlite_backup.BackupNotQuiescent as exc:
        aipol_admin_store.append_external_audit(
            actor=actor, action="database.backup.failed", resource_type="database",
            resource_id="event.db", payload={"reason": str(exc)},
        )
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        aipol_admin_store.append_external_audit(
            actor=actor, action="database.backup.failed", resource_type="database",
            resource_id="event.db", payload={"reason": type(exc).__name__},
        )
        raise
    aipol_admin_store.append_external_audit(
        actor=actor, action="database.backup.completed", resource_type="database",
        resource_id="event.db", payload=result,
    )
    return result


def _check_chat_rate(request: Request) -> None:
    client = _remote_address(request)
    now = time.time()
    with CHAT_RATE_LOCK:
        if len(CHAT_RATE) >= 10_000:
            for key in [key for key, values in CHAT_RATE.items() if not values or now - values[-1] >= 60]:
                CHAT_RATE.pop(key, None)
            if client not in CHAT_RATE and len(CHAT_RATE) >= 10_000:
                raise HTTPException(429, "질문 요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요")
        recent = [value for value in CHAT_RATE.get(client, []) if now - value < 60]
        if len(recent) >= AIPOL_CHAT_RATE_LIMIT:
            raise HTTPException(429, "질문 요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요")
        CHAT_RATE[client] = recent + [now]


def _remote_address(request: Request) -> str:
    """Return the right-most untrusted address behind explicitly trusted proxies.

    Uvicorn must preserve the socket peer.  Only when that peer is in the
    configured CIDRs do we consider X-Forwarded-For, walking the chain from the
    nearest hop so a client-supplied left-most value cannot become the rate key.
    """
    peer_text = request.client.host if request.client else "unknown"
    try:
        peer = ipaddress.ip_address(peer_text)
    except ValueError:
        return peer_text[:128]
    if not TRUSTED_PROXY_NETWORKS or not any(peer in network for network in TRUSTED_PROXY_NETWORKS):
        return peer.compressed
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer.compressed
    try:
        chain = [ipaddress.ip_address(value.strip()) for value in forwarded.split(",")]
    except ValueError:
        return peer.compressed
    for address in reversed(chain + [peer]):
        if not any(address in network for network in TRUSTED_PROXY_NETWORKS):
            return address.compressed
    return peer.compressed


def _registration_remote(request: Request) -> str:
    return _remote_address(request)


def _prune_registration_failures(now: float) -> None:
    cutoff = now - AIPOL_REGISTRATION_FAILURE_WINDOW_SECONDS
    REGISTRATION_GLOBAL_FAILURES[:] = [value for value in REGISTRATION_GLOBAL_FAILURES if value > cutoff]
    for key in list(REGISTRATION_FAILURES):
        recent = [value for value in REGISTRATION_FAILURES[key] if value > cutoff]
        if recent:
            REGISTRATION_FAILURES[key] = recent
        else:
            REGISTRATION_FAILURES.pop(key, None)
    while len(REGISTRATION_FAILURES) > AIPOL_REGISTRATION_RATE_MAX_KEYS:
        oldest = min(REGISTRATION_FAILURES, key=lambda key: REGISTRATION_FAILURES[key][-1])
        REGISTRATION_FAILURES.pop(oldest, None)


def _check_registration_failure_budget(experiment_id: str, remote: str) -> None:
    now = time.time()
    with REGISTRATION_RATE_LOCK:
        _prune_registration_failures(now)
        if (
            len(REGISTRATION_GLOBAL_FAILURES) >= AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET
            or len(REGISTRATION_FAILURES.get((experiment_id, remote), ()))
            >= AIPOL_REGISTRATION_FAILURES_PER_REMOTE
        ):
            raise HTTPException(
                429, "등록 인증 실패가 너무 많습니다. 잠시 뒤 다시 시도해 주세요",
                headers={"Retry-After": str(AIPOL_REGISTRATION_FAILURE_WINDOW_SECONDS)},
            )


def _record_registration_failure(experiment_id: str, remote: str) -> None:
    now = time.time()
    with REGISTRATION_RATE_LOCK:
        _prune_registration_failures(now)
        key = (experiment_id, remote)
        if key not in REGISTRATION_FAILURES and len(REGISTRATION_FAILURES) >= AIPOL_REGISTRATION_RATE_MAX_KEYS:
            oldest = min(REGISTRATION_FAILURES, key=lambda item: REGISTRATION_FAILURES[item][-1])
            REGISTRATION_FAILURES.pop(oldest, None)
        REGISTRATION_FAILURES.setdefault(key, []).append(now)
        REGISTRATION_GLOBAL_FAILURES.append(now)
        REGISTRATION_FAILURES[key][:] = REGISTRATION_FAILURES[key][
            -AIPOL_REGISTRATION_FAILURES_PER_REMOTE:
        ]
        REGISTRATION_GLOBAL_FAILURES[:] = REGISTRATION_GLOBAL_FAILURES[
            -AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET:
        ]


def _clear_registration_failures(experiment_id: str, remote: str) -> None:
    with REGISTRATION_RATE_LOCK:
        REGISTRATION_FAILURES.pop((experiment_id, remote), None)


@app.post("/api/aipol/chat")
def aipol_public_chat(body: dict, request: Request):
    if not AIPOL_CHATBOT_PUBLIC_ENABLED:
        raise HTTPException(404, "챗봇이 비활성화되어 있습니다")
    config = aipol_admin_store.get_chatbot_config()
    if not config["enabled"]:
        raise HTTPException(404, "챗봇이 비활성화되어 있습니다")
    query = body.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise HTTPException(400, "질문은 1~500자 문자열이어야 합니다")
    _check_chat_rate(request)
    try:
        chunks = aipol_admin_store.approved_chunks()
        answer, mode = aipol_chat.answer(
            query.strip(), chunks, config,
            aipol_admin_store.reserve_chatbot_cost_unit,
        )
    except ValueError as exc:
        raise HTTPException(503, "승인 지식의 공개 출처 URL 검증에 실패했습니다") from exc
    except aipol_chat.FoundryUnavailable as exc:
        raise HTTPException(503, "근거형 생성 서비스를 사용할 수 없습니다") from exc
    # Deliberately do not persist or audit the raw query.
    return {
        "answer": answer.answer,
        "abstained": answer.abstained,
        "reason": answer.reason,
        "claims": [asdict(claim) for claim in answer.claims],
        "citations": [asdict(citation) for citation in answer.citations],
        "mode": mode,
        "notice": "승인된 공개 지식에 근거한 안내이며 공식 정책 결정이 아닙니다.",
    }


def _require_review_exchange_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    approved_origin = os.environ.get("AIPOL_PUBLIC_ORIGIN", "")
    if origin != approved_origin or urlparse(origin).scheme != "https":
        raise HTTPException(403, "검토 인증 요청 출처가 올바르지 않습니다")


def _check_review_exchange_rate(request: Request) -> None:
    remote = _remote_address(request)
    now = time.time()
    with REVIEW_EXCHANGE_RATE_LOCK:
        if len(REVIEW_EXCHANGE_RATE) >= 10_000:
            for key in [
                key for key, values in REVIEW_EXCHANGE_RATE.items()
                if not values or now - values[-1] >= 60
            ]:
                REVIEW_EXCHANGE_RATE.pop(key, None)
            if remote not in REVIEW_EXCHANGE_RATE and len(REVIEW_EXCHANGE_RATE) >= 10_000:
                raise HTTPException(429, "검토 인증 요청이 너무 많습니다")
        recent = [value for value in REVIEW_EXCHANGE_RATE.get(remote, []) if now - value < 60]
        if len(recent) >= AIPOL_REVIEW_EXCHANGE_RATE_LIMIT:
            raise HTTPException(429, "검토 인증 요청이 너무 많습니다", headers={"Retry-After": "60"})
        REVIEW_EXCHANGE_RATE[remote] = recent + [now]


@app.post("/api/aipol/review/exchange")
def aipol_review_exchange(body: dict, request: Request):
    _require_exact_contract(
        body, {"experiment_id", "review_token", "exchange_nonce"}, set(), "review exchange"
    )
    if not all(
        isinstance(body.get(key), str)
        for key in ("experiment_id", "review_token", "exchange_nonce")
    ):
        raise HTTPException(400, "review exchange fields must be strings")
    _require_review_exchange_origin(request)
    _check_review_exchange_rate(request)
    session_token = _aipol_call(
        aipol_store.exchange_review_token,
        body["experiment_id"],
        body["review_token"],
        body["exchange_nonce"],
    )
    response = Response(
        status_code=204,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.set_cookie(
        "aipol_review_session",
        session_token,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/api/aipol/review",
    )
    return response


@app.get("/api/aipol/review/planning/catalog")
def aipol_planning_review_catalog(stage: str = "intro"):
    result = _aipol_call(aipol_store.get_planning_review_catalog, stage)
    return JSONResponse(
        result,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@app.get("/api/aipol/review/{experiment_id}/catalog")
def aipol_review_catalog(experiment_id: str, request: Request, stage: str = "intro"):
    session_token = request.cookies.get("aipol_review_session", "")
    result = _aipol_call(
        aipol_store.get_review_catalog, experiment_id, session_token, stage
    )
    return JSONResponse(
        result,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@app.post("/api/aipol/experiments/{experiment_id}/participants")
def aipol_register(experiment_id: str, body: dict, request: Request):
    """공개 등록은 실제 참가자만 허용한다. 합성 입력은 인증된 진행자 경로로 분리."""
    remote = _registration_remote(request)
    _check_registration_failure_budget(experiment_id, remote)
    _require_exact_contract(
        body,
        {"admission_code", "registration_nonce", "idempotency_key"},
        set(),
        "participant registration",
    )
    if not all(isinstance(body.get(key), str) for key in body):
        raise HTTPException(400, "participant registration fields must be strings")
    _aipol_call(aipol_store._validate_admission_code, body["admission_code"])
    try:
        result = _aipol_call(
            aipol_store.register_participant,
            experiment_id,
            "real",
            admission_code=str(body.get("admission_code") or ""),
            registration_nonce=str(body.get("registration_nonce") or ""),
            idempotency_key=str(body.get("idempotency_key") or ""),
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            _record_registration_failure(experiment_id, remote)
        raise
    replayed = bool(result.pop("_registration_replayed", False))
    if not replayed:
        _clear_registration_failures(experiment_id, remote)
    return result


@app.post("/api/aipol/experiments/{experiment_id}/participants/recover")
def aipol_recover_participant(experiment_id: str, body: dict, request: Request):
    remote = _registration_remote(request)
    _check_registration_failure_budget(experiment_id, remote)
    _require_exact_contract(body, {"recovery_code"}, set(), "participant recovery")
    recovery_code = body.get("recovery_code")
    if not isinstance(recovery_code, str):
        raise HTTPException(400, "recovery_code must be a string")
    try:
        result = _aipol_call(
            aipol_store.recover_participant, experiment_id, recovery_code
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            _record_registration_failure(experiment_id, remote)
        raise
    _clear_registration_failures(experiment_id, remote)
    return result


@app.get("/api/aipol/experiments/{experiment_id}/current")
def aipol_current(experiment_id: str, x_participant_token: str = Header(default="")):
    return _aipol_call(aipol_store.participant_current, experiment_id, x_participant_token)


@app.post("/api/aipol/experiments/{experiment_id}/consent")
def aipol_consent(
    experiment_id: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    return _aipol_call(
        aipol_store.record_consent,
        experiment_id,
        x_participant_token,
        consent_version=str(body.get("consent_version") or ""),
        affirmed=body.get("affirmed") is True,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/research-profile")
def aipol_research_profile(
    experiment_id: str, body: dict, x_participant_token: str = Header(default="")
):
    _require_exact_contract(
        body,
        {"profile", "consented", "consent_version", "expected_revision", "idempotency_key"},
        set(),
        "research profile",
    )
    if body.get("consented") is True and not isinstance(body.get("profile"), dict):
        raise HTTPException(400, "profile은 네 개의 구간 ID 객체여야 합니다")
    if body.get("consented") is not True and body.get("profile") not in (None, {}):
        raise HTTPException(400, "동의하지 않은 경우 profile을 제출할 수 없습니다")
    return _aipol_call(
        aipol_store.record_research_profile,
        experiment_id,
        x_participant_token,
        profile=body["profile"],
        consented=body.get("consented") is True,
        consent_version=str(body.get("consent_version") or ""),
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/t6-ack")
def aipol_t6_ack(
    experiment_id: str, body: dict, x_participant_token: str = Header(default="")
):
    _require_exact_contract(
        body,
        {"content_hash", "expected_revision", "idempotency_key"},
        set(),
        "T6 acknowledgement",
    )
    if not isinstance(body.get("content_hash"), str):
        raise HTTPException(400, "content_hash는 문자열이어야 합니다")
    return _aipol_call(
        aipol_store.acknowledge_t6_snapshot,
        experiment_id,
        x_participant_token,
        content_hash_value=body["content_hash"],
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/exposures/{stage}")
def aipol_exposure(
    experiment_id: str,
    stage: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    if body.get("completion_receipt") is not None and not isinstance(body["completion_receipt"], dict):
        raise HTTPException(400, "completion_receipt must be a JSON object")
    return _aipol_call(
        aipol_store.record_exposure,
        experiment_id,
        x_participant_token,
        stage,
        read_ack=body.get("read_ack") is True,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
        completion_receipt=body.get("completion_receipt"),
    )


@app.post("/api/aipol/experiments/{experiment_id}/exposures/{stage}/open")
def aipol_exposure_open(
    experiment_id: str,
    stage: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    return _aipol_call(
        aipol_store.record_exposure_open,
        experiment_id,
        x_participant_token,
        stage,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/measurements/{measurement_id}")
def aipol_measurement(
    experiment_id: str,
    measurement_id: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    choice = body.get("choice")
    if choice is not None and not isinstance(choice, str):
        raise HTTPException(400, "choice는 문자열 또는 null이어야 합니다")
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise HTTPException(400, "선택 이유는 문자열 또는 null이어야 합니다")
    if reason is not None and len(reason) > 2_000:
        raise HTTPException(400, "선택 이유는 2,000자 이하여야 합니다")
    stance = body.get("stance")
    if stance is not None and stance not in ("accept", "conditional", "reject"):
        raise HTTPException(400, "stance는 accept, conditional, reject 또는 null이어야 합니다")
    secondary = body.get("secondary_evaluation")
    if secondary is not None and not isinstance(secondary, dict):
        raise HTTPException(400, "secondary_evaluation은 JSON 객체 또는 null이어야 합니다")
    option_assessments = body.get("option_assessments")
    if option_assessments is not None and not isinstance(option_assessments, dict):
        raise HTTPException(400, "option_assessments는 JSON 객체 또는 null이어야 합니다")
    if isinstance(option_assessments, dict):
        for assessment in option_assessments.values():
            if not isinstance(assessment, dict):
                continue
            nested_reason = assessment.get("reason")
            if isinstance(nested_reason, str) and len(nested_reason) > 2_000:
                raise HTTPException(400, "안별 사유는 2,000자 이하여야 합니다")
    return _aipol_call(
        aipol_store.submit_measurement,
        experiment_id,
        x_participant_token,
        measurement_id,
        choice=choice,
        reason=reason,
        confidence=body.get("confidence"),
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
        secondary_evaluation=secondary,
        stance=stance,
        option_assessments=option_assessments,
    )


@app.post("/api/aipol/experiments/{experiment_id}/policy-options-ack")
def aipol_policy_options_ack(
    experiment_id: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    content_hash_value = body.get("content_hash")
    if not isinstance(content_hash_value, str):
        raise HTTPException(400, "content_hash는 문자열이어야 합니다")
    return _aipol_call(
        aipol_store.acknowledge_policy_options,
        experiment_id,
        x_participant_token,
        content_hash_value=content_hash_value,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/public-results/{result_stage}/ack")
def aipol_public_result_ack(
    experiment_id: str,
    result_stage: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    _require_exact_contract(
        body,
        {"content_hash", "expected_revision", "idempotency_key"},
        set(),
        "public result acknowledgement",
    )
    content_hash_value = body.get("content_hash")
    if not isinstance(content_hash_value, str):
        raise HTTPException(400, "content_hash는 문자열이어야 합니다")
    return _aipol_call(
        aipol_store.acknowledge_public_result,
        experiment_id,
        x_participant_token,
        result_stage,
        content_hash_value=content_hash_value,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/audience-discussion-ack")
def aipol_audience_discussion_ack(
    experiment_id: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    _require_exact_contract(
        body,
        {"expected_revision", "idempotency_key"},
        set(),
        "audience discussion acknowledgement",
    )
    return _aipol_call(
        aipol_store.acknowledge_audience_discussion,
        experiment_id,
        x_participant_token,
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


@app.post("/api/aipol/experiments/{experiment_id}/withdraw")
def aipol_withdraw(
    experiment_id: str,
    body: dict,
    x_participant_token: str = Header(default=""),
):
    return _aipol_call(
        aipol_store.withdraw_participant,
        experiment_id,
        x_participant_token,
        reason=body.get("reason"),
        expected_revision=_expected_revision(body),
        idempotency_key=str(body.get("idempotency_key") or ""),
    )


app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
