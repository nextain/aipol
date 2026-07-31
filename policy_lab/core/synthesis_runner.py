"""[2] AI 숙의 — LLM sub-runner (RFC-0003 §3·§7).

``synthesis.py`` 의 결정론 코어를 감싸는 **비결정 오케스트레이션**. RFC §7대로 [2]의
fan-out/fan-in DAG를 단일 stage 내부의 sub-runner로 캡슐화한다 — 외부엔 통합안 1 artifact만
노출하되, 내부는:

    원본 응답 → claim 추출(추출기) → 4 플래그십 독립 초안(서로 안 봄)
              → 교차 적대 리뷰(각도 분담) → cover 판정(판정기 ≥2)
              → synthesis.merge()(결정론) → MergedProposal

LLM 호출은 모두 ``ChatClient`` 한 곳을 지난다(의존 역전). 실 구현은 any-llm gateway를
감싸고(``AnyLLMClient``), 테스트는 stub을 주입한다 — 클라우드 비용 없이 DAG·가드·파싱을
검증하기 위해서다. 모델 교체(독파모)는 ``Flagship``/``judges`` 설정 한 줄.

가드는 호출 **전에** 발화한다(§6): 초안 ≥3·회사 ≥3, 초안가 ∩ 판정기 = ∅.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Protocol

from .responses import CitizenResponse, Stance
from .synthesis import (
    Claim,
    Clause,
    Draft,
    CoverJudgment,
    MergedProposal,
    merge,
    assert_independent_drafts,
    assert_judge_separation,
    assert_reflection_completeness,
)


# ── LLM 경계 (의존 역전: 코어는 any-llm 을 모른다) ──────────────────────


class ChatClient(Protocol):
    """단일 LLM 호출 경계. 실 구현=any-llm, 테스트=stub.

    한 번의 호출 = (모델, 메시지) → 텍스트. provider 는 any-llm 라우팅용(없으면 model 추론).
    """

    def __call__(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        provider: str | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class Flagship:
    """[2] 초안가 한 자리 — 모델·회사·any-llm provider."""

    model: str
    company: str           # 독립 학습계보 (§2 회사 ≥3 강제 재료)
    provider: str | None = None


@dataclass
class SynthesisConfig:
    """[2] sub-runner 설정. 모델 교체(독파모)는 여기만 바꾼다."""

    flagships: tuple[Flagship, ...]              # 독립 초안가 (4)
    judges: tuple[str, ...]                       # cover 판정기 (≥2, 초안가와 분리)
    extractor: str                                # claim 추출기
    judge_providers: dict[str, str] = field(default_factory=dict)
    extractor_provider: str | None = None
    majority_support: int = 0                     # '다수 claim' 기준 (호출자 명시)
    minority_threshold: int = 0                   # 소수 강제포함 지지 하한
    temperature: float = 0.4

    def drafter_models(self) -> set[str]:
        return {f.model for f in self.flagships}


# ── 산출 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Review:
    """한 초안에 대한 교차 적대 리뷰 (각도 분담: 편향/과장/은폐)."""

    target_model: str        # 리뷰 대상 초안
    reviewer_model: str      # 리뷰어 (다른 회사)
    angle: str               # bias | overclaim | concealment
    findings: str


@dataclass
class SynthesisResult:
    """sub-runner 전체 산출 — 통합안 + 모든 비결정 흔적(감사용)."""

    claims: tuple[Claim, ...]
    drafts: tuple[Draft, ...]
    reviews: tuple[Review, ...]
    judgments: tuple[CoverJudgment, ...]
    merged: MergedProposal


# ── 파싱 (LLM 텍스트 → 구조; 관대하되 실패는 드러냄) ────────────────────


def _extract_json(text: str):
    """LLM 응답에서 **첫 유효 JSON** 객체/배열을 뽑는다. ```json 펜스·앞뒤 잡설 허용.

    greedy 정규식(첫 `{`~마지막 `}`)은 텍스트 속 괄호·다중 블록에서 오버런한다(리뷰 #2).
    대신 각 여는 괄호에서 ``raw_decode`` 로 스캔해 처음 파싱되는 블록을 반환 — 진짜 '첫 JSON'.
    """
    if text is None:
        raise ValueError("LLM content=None — reasoning-only·tool_call·length 컷 의심(동시성 아님)")
    if not text.strip():
        raise ValueError("LLM 빈 응답 — 동시성 간섭/한도 의심(RFC §7 동시성 가드)")
    # thinking 판정기(kanana-thinking 등)는 <think> 안에서 가설 JSON을 먼저 낼 수 있다 —
    # 그걸 verdict 로 잡으면 판정이 뒤집힌다(실측, 2026-06-27). </think> 뒤 최종 답만 본다.
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    fenced = re.search(r"```(?:json|JSON)?\s*(.+?)```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else text
    dec = json.JSONDecoder()
    for i, ch in enumerate(blob):
        if ch in "[{":
            try:
                obj, _ = dec.raw_decode(blob[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError(f"유효 JSON 못 찾음: {text[:120]!r}")


def _req(d: dict, key: str, ctx: str):
    """LLM 산출 dict에서 필수 키를 꺼내되, 누락 시 어느 항목인지 밝힌다(리뷰 #3).

    직접 인덱싱의 raw KeyError 대신 어느 단계·어느 항목이 깨졌는지 attribution.
    """
    if not isinstance(d, dict) or key not in d:
        raise ValueError(f"{ctx}: 필수 키 '{key}' 누락 — LLM 산출 형식 위반 ({str(d)[:80]!r})")
    return d[key]


# ── 단계 함수 (각각 ChatClient 를 지남) ─────────────────────────────────


_EXTRACT_SYS = (
    "당신은 정책 숙의의 claim 추출기다. 시민들의 자유 응답(조건부 수용의 조건, 거부 사유)에서 "
    "정책에 반영 가능한 개별 '주장(claim)'을 추출한다. 같은 취지는 하나로 묶고, 그 claim을 "
    "제기한 시민 수를 센다. 창작·일반화 금지 — 원문에 근거가 있어야 한다.\n"
    '출력은 JSON 배열만: [{"cid","text","support","segments":[..]}]'
)


def extract_claims(client: ChatClient, responses: list[CitizenResponse], cfg: SynthesisConfig) -> list[Claim]:
    """원본 자유텍스트 → 시민 claim (추출기 1모델, 판정기·초안가와 분리 권장 §9).

    조건부 수용의 조건 텍스트 + 거부 사유가 합치기의 재료(§1 '조건 텍스트가 풍부해야').
    """
    corpus = []
    for cr in responses:
        for r in cr.responses.values():
            if r.text.strip() and r.stance in (Stance.CONDITIONAL, Stance.REJECT):
                corpus.append(f"[{cr.segment}/{r.proposal_id}/{r.stance.value}] {r.text.strip()}")
    user = "다음 시민 응답에서 claim을 추출하라:\n" + "\n".join(corpus)
    out = client(
        cfg.extractor,
        [{"role": "system", "content": _EXTRACT_SYS}, {"role": "user", "content": user}],
        temperature=cfg.temperature,
        provider=cfg.extractor_provider,
    )
    data = _extract_json(out)
    if not isinstance(data, list):
        raise ValueError(f"claim 추출: 배열이 와야 함 ({str(data)[:80]!r})")
    out_claims = []
    for d in data:
        pids = tuple(str(p) for p in d.get("pids", []))
        # support 미제공 시 pids 수로 보강(둘 다 없으면 0)
        support = int(d["support"]) if "support" in d else len(pids)
        out_claims.append(
            Claim(
                cid=str(_req(d, "cid", "claim 추출")),
                text=str(_req(d, "text", "claim 추출")),
                support=support,
                segments=tuple(d.get("segments", [])),
                pids=pids,
            )
        )
    return out_claims


_DRAFT_SYS = (
    "당신은 정책 통합안 초안가다. 시민 claim 목록을 보고, 가능한 한 많은 claim을 정직하게 "
    "반영하는 단일 통합안을 조항 단위로 작성한다. 다른 초안가의 안은 보지 못한다(독립). "
    "양립불가는 봉합하지 말고 트레이드오프로 남겨라.\n"
    '출력은 JSON: {"clauses":[{"clause_id","text"}]}'
)


def draft_proposals(client: ChatClient, claims: list[Claim], cfg: SynthesisConfig) -> list[Draft]:
    """4 플래그십이 같은 claim을 보고 **독립으로** 통합안 초안 (서로 안 봄, §3)."""
    assert_independent_drafts(list(cfg.flagships), min_drafts=3, min_companies=3)
    claim_block = "\n".join(f"- ({c.cid}, 지지 {c.support}) {c.text}" for c in claims)
    drafts: list[Draft] = []
    for f in cfg.flagships:
        out = client(
            f.model,
            [{"role": "system", "content": _DRAFT_SYS},
             {"role": "user", "content": f"시민 claim:\n{claim_block}\n\n통합안 초안을 작성하라."}],
            temperature=cfg.temperature,
            provider=f.provider,
        )
        data = _extract_json(out)
        raw = _req(data, "clauses", f"초안({f.model})")
        if not isinstance(raw, list):
            raise ValueError(f"초안({f.model}): clauses 는 배열이어야 함 ({str(raw)[:80]!r})")
        clauses = tuple(
            Clause(str(_req(c, "clause_id", f"초안({f.model})")), str(_req(c, "text", f"초안({f.model})")))
            for c in raw
        )
        drafts.append(Draft(model=f.model, company=f.company, clauses=clauses))
    return drafts


_ANGLES = ("bias", "overclaim", "concealment")  # 편향 / 과장 / 은폐
_REVIEW_SYS = {
    "bias": "당신은 적대 리뷰어다. 이 통합안이 특정 집단·입장으로 **편향**됐는지만 본다.",
    "overclaim": "당신은 적대 리뷰어다. 이 통합안이 효과·합의를 **과장**했는지만 본다.",
    "concealment": "당신은 적대 리뷰어다. 이 통합안이 미반영 claim·트레이드오프를 **은폐**했는지만 본다.",
}


def cross_review(client: ChatClient, drafts: list[Draft], cfg: SynthesisConfig) -> list[Review]:
    """교차 적대 리뷰 — 각 초안을 다른 회사 리뷰어가 각도 분담해 본다(§3).

    리뷰는 감사 흔적(provenance)으로 남고 [3a] 가시화의 '리뷰 지적' 재료다.
    """
    reviews: list[Review] = []
    fs = list(cfg.flagships)
    for i, target in enumerate(drafts):
        reviewer = fs[(i + 1) % len(fs)]  # 다음 회사 (자기 회사 리뷰 회피)
        angle = _ANGLES[i % len(_ANGLES)]
        body = "\n".join(f"[{c.clause_id}] {c.text}" for c in target.clauses)
        out = client(
            reviewer.model,
            [{"role": "system", "content": _REVIEW_SYS[angle]},
             {"role": "user", "content": f"통합안:\n{body}\n\n지적을 간결히 쓰라."}],
            temperature=cfg.temperature,
            provider=reviewer.provider,
        )
        reviews.append(Review(target.model, reviewer.model, angle, out.strip()))
    return reviews


_JUDGE_SYS = (
    "당신은 cover 판정기다. 주어진 시민 claim이 통합안의 어느 조항에 의해 **실제로 반영**됐는지 "
    "판정한다. 막연한 관련이 아니라 그 조항이 claim을 다뤄야 cover다. 자기 채점 아님(초안 작성에 "
    "참여하지 않음).\n"
    '출력은 JSON: {"covered":true/false,"clause_id":"...(covered면 필수)"}'
)


def judge_cover(client: ChatClient, claims: list[Claim], drafts: list[Draft], cfg: SynthesisConfig) -> list[CoverJudgment]:
    """판정기 ≥2 가 각 (claim, 초안)에 cover 여부 판정 → CoverJudgment (§3).

    판정기는 초안가와 분리(§6). 한 (claim, 초안)에 판정기 표가 모이고, 불일치는 코어가
    '불확실'로 노출한다.
    """
    assert_judge_separation(cfg.drafter_models(), set(cfg.judges))
    out: list[CoverJudgment] = []
    for c in claims:
        for d in drafts:
            body = "\n".join(f"[{cl.clause_id}] {cl.text}" for cl in d.clauses)
            for jm in cfg.judges:
                resp = client(
                    jm,
                    [{"role": "system", "content": _JUDGE_SYS},
                     {"role": "user", "content": f"claim: {c.text}\n\n통합안 조항:\n{body}"}],
                    temperature=0.0,
                    provider=cfg.judge_providers.get(jm),
                )
                v = _extract_json(resp)
                covered = bool(_req(v, "covered", f"판정({jm}/{d.model})"))
                out.append(
                    CoverJudgment(
                        claim_id=c.cid,
                        draft_model=d.model,
                        judge_model=jm,
                        covered=covered,
                        clause_id=str(v.get("clause_id", "")) if covered else "",
                    )
                )
    return out


def run_synthesis(client: ChatClient, responses: list[CitizenResponse], cfg: SynthesisConfig) -> SynthesisResult:
    """[2] 전체 오케스트레이션 — 외부엔 통합안 1개, 내부는 DAG 전부 감사 가능.

    가드는 각 단계 진입에서 발화한다. 결정론은 마지막 ``merge()`` 산술뿐.
    """
    claims = extract_claims(client, responses, cfg)
    drafts = draft_proposals(client, claims, cfg)       # assert_independent_drafts 내부
    reviews = cross_review(client, drafts, cfg)
    judgments = judge_cover(client, claims, drafts, cfg)  # assert_judge_separation 내부
    merged = merge(
        claims, drafts, judgments,
        majority_support=cfg.majority_support,
        minority_threshold=cfg.minority_threshold,
    )
    # [2] 완전성 가드를 라이브 경로에서 발화(리뷰 C3: 선언만 되고 미배선이던 것)
    assert_reflection_completeness(merged, claims, majority_support=cfg.majority_support)
    return SynthesisResult(
        claims=tuple(claims), drafts=tuple(drafts),
        reviews=tuple(reviews), judgments=tuple(judgments), merged=merged,
    )


# ── 실 구현: any-llm gateway 어댑터 (테스트는 import 안 함) ──────────────


class AnyLLMClient:
    """``ChatClient`` 의 any-llm 구현. 실험 단계에서만 쓴다(클라우드 호출).

    any-llm 의 provider 통합으로 codex/gemini/glm/claude → 독파모 교체가 설정 한 줄.
    동시성 가드: 같은 백엔드 공유 시 호출을 직렬화해야 한다(§7, qwen 89% 무효 교훈) —
    호출자가 순차 실행으로 보장(이 어댑터는 단발만).
    """

    def __init__(self, *, default_provider: str | None = None):
        self.default_provider = default_provider
        self._lock = threading.Lock()

    def __call__(self, model, messages, *, temperature=0.7, provider=None):
        from any_llm import completion  # 지연 import — 코어/테스트 경로 비오염

        # 동시성 가드를 honor-system 주석이 아니라 코드 불변식으로(리뷰 #4): 같은 백엔드
        # 공유 중 동시 호출 = 빈 응답(qwen 89% 교훈, §7). non-blocking 으로 재진입 거부.
        if not self._lock.acquire(blocking=False):
            raise RuntimeError(
                "AnyLLMClient 동시 호출 감지 — 추론 백엔드 공유 중 직렬 실행 강제(§7). "
                "fan-out 최적화 시 백엔드별 별도 클라이언트/직렬화 필요"
            )
        try:
            resp = completion(
                model=model,
                messages=messages,
                provider=provider or self.default_provider,
                temperature=temperature,
            )
        finally:
            self._lock.release()
        content = resp.choices[0].message.content
        if content is None:
            # None 을 ""로 뭉개면 _extract_json 이 '동시성/한도'로 오진(리뷰 #1). 구분해 올림.
            raise ValueError(
                f"{model}: content=None — reasoning-only·tool_call·length 컷 의심(동시성 아님). "
                "응답 구조 확인 필요"
            )
        return content
