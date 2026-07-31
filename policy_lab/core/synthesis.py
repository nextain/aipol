"""[2] AI 숙의 — claim 카운트 합치기의 **결정론 코어** (RFC-0003 §3).

RFC §3의 핵심 통찰: claim↔조항 매칭은 의미 판정이라 모델(편향)이 필요하고 비결정이다.
**진짜 결정론은 cover 카운트·임계 비교(산술)뿐**이다. 이 모듈은 그 산술만 담는다.

따라서 경계가 둘로 갈린다:
  - **비결정·감사 대상** (이 모듈 밖, any-llm 경유 다음 벽돌):
    원본 자유텍스트 → claim 추출 · 4 플래그십 독립 초안 · 교차 적대리뷰 ·
    "초안 D가 claim C를 cover하는가" 판정.
  - **결정론·이 모듈** (산술):
    판정 표(``CoverJudgment``)를 입력으로 받아 → cover 카운트 k ∈ {0..n} →
    임계 규칙으로 disposition 분류 → provenance + 정직 노출(미반영·추가숙의).

판정기는 초안가와 분리된다(§6 ``assert_judge_separation``). 판정 ≥2 모델 불일치는
"불확실"로 노출하지 봉합하지 않는다. 이 분리·노출·provenance가 비결정 매칭을 **검증·반증
가능**하게 만든다 — "결정론"이라는 단어를 신뢰 근거로 쓰지 않는다(§3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .guards import GuardViolation


def _norm(s: str) -> str:
    """모델·회사 식별자 정규화 — 대소문자·둘레공백 차이로 가드 우회 차단(리뷰 M1·M2)."""
    return s.strip().casefold()


# ── 입력 단위 (비결정 LLM 층이 생산, 이 모듈은 소비만) ──────────────────


@dataclass(frozen=True)
class Claim:
    """원본 자유텍스트(조건부 조건·거부 사유)에서 추출한 **시민 claim**.

    합치기의 닻은 AI 초안의 조항이 아니라 이 claim이다(§3). ``support`` 는 이 claim을
    제기·지지한 시민 수(원본 빈도) — 형평 강제포함·다수 분류의 산술 기준.
    """

    cid: str
    text: str
    support: int  # 원본에서 이 claim을 제기/지지한 시민 수
    segments: tuple[str, ...] = ()  # 어느 집단에서 나왔나 (형평 추적)
    pids: tuple[str, ...] = ()      # 이 claim을 제기한 시민 pid (있으면 [3b] 개인 경로 재료)

    def __post_init__(self) -> None:
        if self.support < 0:
            raise ValueError(f"{self.cid}: support 는 음수일 수 없음 ({self.support})")


@dataclass(frozen=True)
class Clause:
    """한 초안(통합안)이 담은 조항."""

    clause_id: str
    text: str


@dataclass(frozen=True)
class Draft:
    """한 플래그십이 원본 claim들을 보고 **독립으로** 만든 통합안 초안(서로 안 봄, §3).

    ``company`` = 독립 학습계보. §2/§6의 "독립 회사 ≥3" 강제는 이 필드로 센다 —
    같은 회사 4모델은 다양성이 아니다.
    """

    model: str
    company: str
    clauses: tuple[Clause, ...] = ()


@dataclass(frozen=True)
class CoverJudgment:
    """판정기 한 표: "초안 ``draft_model`` 이 claim ``claim_id`` 를 cover하는가".

    판정기(``judge_model``)는 초안가와 분리된다(§6). 한 (draft, claim) 쌍에 ≥2 판정기
    표가 모이고, 불일치 시 그 쌍은 cover로 세지 않고 '불확실'로 노출한다.
    ``covered`` 가 참이면 ``clause_id`` 로 어느 조항이 cover했는지 가리킨다(provenance 재료).
    """

    claim_id: str
    draft_model: str
    judge_model: str
    covered: bool
    clause_id: str = ""

    def __post_init__(self) -> None:
        if self.covered and not self.clause_id:
            raise ValueError(
                f"{self.claim_id}/{self.draft_model}: cover 한다면서 조항(clause_id) 미지정 "
                "(§3 provenance 4-tuple 은 조항 링크 필수)"
            )


# ── 산출 단위 (결정론 산술의 결과) ──────────────────────────────────────


class Disposition(str, Enum):
    """한 claim이 통합안에서 받은 처분 — 모두 **정직하게 노출**된다(§3 군집 무시 금지)."""

    REFLECTED = "reflected"              # k≥2 → 통합안 반영
    FORCED_MINORITY = "forced_minority"  # k=1 이나 지지율 임계 → 형평 위해 강제 포함
    UNREFLECTED = "unreflected"          # 미반영 (사유 노출)
    NEEDS_MORE = "needs_more"            # k=0 다수 claim → 추가 숙의 필요

    @property
    def adopted(self) -> bool:
        """통합안에 들어가는 처분인가 (조항 링크 필수 대상)."""
        return self in (Disposition.REFLECTED, Disposition.FORCED_MINORITY)


@dataclass(frozen=True)
class Provenance:
    """사후 감사 단위 — (claim, 조항들, cover수, 판정모델들, 불확실 초안) (§3 4-tuple 확장).

    매칭 '정확성'은 코드로 강제 못 한다(§6). 대신 이 구조를 남겨 사람이 사후 감사한다.
    """

    claim_id: str
    cover: int                              # k ∈ {0..n_drafts}
    clause_ids: tuple[str, ...]             # 이 claim을 cover한 조항들(드래프트 가로질러)
    judge_models: tuple[str, ...]           # 판정에 참여한 판정기들
    uncertain_drafts: tuple[str, ...] = ()  # 판정기 불일치한 초안들 (불확실 노출)


@dataclass(frozen=True)
class MergeDecision:
    """한 claim에 대한 합치기 결정 (claim 1개 = 결정 1개)."""

    claim: Claim
    cover: int
    robust: bool                # k == n_drafts (모든 초안이 cover)
    disposition: Disposition
    provenance: Provenance
    reason: str = ""            # 미반영/추가숙의/강제포함 사유 (정직 노출)


@dataclass
class MergedProposal:
    """합치기 산출 통합안 + 정직 노출 묶음.

    통합안만이 아니라 미반영·추가숙의·불확실까지 **같은 데이터 레벨**로 안고 다닌다 —
    [3a] 가시화가 이를 숨길 수 없게(§1·§6 '포장 금지 = 구조 노출').
    """

    decisions: tuple[MergeDecision, ...]
    drafts: tuple[Draft, ...]

    def _by(self, *disp: Disposition) -> list[MergeDecision]:
        return [d for d in self.decisions if d.disposition in disp]

    def reflected(self) -> list[MergeDecision]:
        return self._by(Disposition.REFLECTED, Disposition.FORCED_MINORITY)

    def unreflected(self) -> list[MergeDecision]:
        return self._by(Disposition.UNREFLECTED)

    def needs_more(self) -> list[MergeDecision]:
        return self._by(Disposition.NEEDS_MORE)

    def uncertain(self) -> list[MergeDecision]:
        """판정기 불일치가 하나라도 있는 결정 (불확실 노출)."""
        return [d for d in self.decisions if d.provenance.uncertain_drafts]

    def adopted_clause_ids(self) -> set[str]:
        """통합안에 실제 들어간 조항 id 집합 (채택 처분의 provenance에서)."""
        out: set[str] = set()
        for d in self.reflected():
            out.update(d.provenance.clause_ids)
        return out


# ── 결정론 산술: cover 카운트 + 임계 규칙 ────────────────────────────────


def _cover_for_claim(
    claim_id: str, judgments: list[CoverJudgment]
) -> tuple[int, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """한 claim의 cover 카운트 (이 claim에 관한 판정표만 받음).

    초안별로 판정기 표를 모은다. 한 초안에 대해:
      - 모든 판정기가 cover=True 로 만장일치 → 그 초안은 cover (+1), 조항 기록
      - 만장일치 아님(불일치) → cover 로 세지 않고 ``uncertain_drafts`` 에 노출
      - 모두 cover=False → cover 아님
    반환: (cover수 k, 조항ids, 판정기들, 불확실 초안들)
    """
    by_draft: dict[str, list[CoverJudgment]] = {}
    judges: set[str] = set()
    for j in judgments:
        if j.claim_id != claim_id:
            continue
        by_draft.setdefault(j.draft_model, []).append(j)
        judges.add(j.judge_model)

    cover = 0
    clause_ids: list[str] = []
    uncertain: list[str] = []
    for draft_model, votes in by_draft.items():
        yes = [v for v in votes if v.covered]
        no = [v for v in votes if not v.covered]
        if yes and no:
            uncertain.append(draft_model)  # 판정기 불일치 → 불확실
        elif yes and not no:
            cover += 1
            clause_ids.extend(v.clause_id for v in yes if v.clause_id)
        # else: 모두 no → cover 아님
    # 조항 id 중복 제거(정렬로 결정론 보존)
    return cover, tuple(sorted(set(clause_ids))), tuple(sorted(judges)), tuple(sorted(uncertain))


def merge(
    claims: list[Claim],
    drafts: list[Draft],
    judgments: list[CoverJudgment],
    *,
    majority_support: int,
    minority_threshold: int,
) -> MergedProposal:
    """claim 카운트 합치기 (§3) — **이 함수가 [2]의 유일한 결정론 부분**.

    규칙(§3, 같은 입력 → 같은 출력):
      - k ≥ 2            → REFLECTED (k == n_drafts 면 robust)
      - k == 1 이고 지지율 ≥ ``minority_threshold`` → FORCED_MINORITY (소수 강제포함)
      - k == 0 이고 지지율 ≥ ``majority_support``   → NEEDS_MORE (추가 숙의)
      - 그 외           → UNREFLECTED

    임계는 호출자가 명시한다(자리표시자 마법수 금지). ``majority_support`` = '다수 claim'
    기준(이상이면 반드시 분류돼야 함, §6 반영 추적). ``minority_threshold`` = 소수라도
    형평상 끌어올릴 지지 하한.

    불변식 ``minority_threshold ≤ majority_support`` (리뷰 §3): 뒤집히면 다수 claim(지지 ≥
    majority)이 k=1일 때 minority 게이트에 먼저 걸려 '임계 미달' UNREFLECTED 로 조용히 샌다.
    """
    if minority_threshold > majority_support:
        raise ValueError(
            f"minority_threshold({minority_threshold}) > majority_support({majority_support}) — "
            "다수 k=1 claim이 미반영으로 샘. minority_threshold ≤ majority_support 여야 (§3)"
        )
    n = len(drafts)
    decisions: list[MergeDecision] = []
    for c in claims:
        k, clause_ids, judge_models, uncertain = _cover_for_claim(c.cid, judgments)
        prov = Provenance(
            claim_id=c.cid,
            cover=k,
            clause_ids=clause_ids,
            judge_models=judge_models,
            uncertain_drafts=uncertain,
        )
        robust = k == n and n > 0
        if k >= 2:
            disp, reason = Disposition.REFLECTED, ""
        elif k == 1 and c.support >= minority_threshold:
            disp = Disposition.FORCED_MINORITY
            reason = f"소수(모델 {k}/{n})지만 지지 {c.support}≥{minority_threshold} → 형평 강제포함"
        elif k == 0 and c.support >= majority_support:
            disp = Disposition.NEEDS_MORE
            reason = f"다수(지지 {c.support})이나 어떤 초안도 미반영 → 추가 숙의"
        else:
            disp = Disposition.UNREFLECTED
            reason = f"cover {k}/{n}, 지지 {c.support} — 임계 미달"
        decisions.append(
            MergeDecision(
                claim=c, cover=k, robust=robust, disposition=disp, provenance=prov, reason=reason
            )
        )
    return MergedProposal(decisions=tuple(decisions), drafts=tuple(drafts))


# ── §6 가드 (코드 강제) ─────────────────────────────────────────────────


def assert_independent_drafts(
    drafts: list[Draft], *, min_drafts: int = 3, min_companies: int = 3
) -> None:
    """단일 합성 금지 (§6): 초안 ≥3 **이며 독립 회사 ≥3**.

    같은 회사 4모델은 교차 다양성이 아니다 — 같은 학습계보는 같이 틀린다(리뷰 m2).
    독파모 교체 시도도 이 하한을 깨면 안 된다.
    """
    if len(drafts) < min_drafts:
        raise GuardViolation(
            f"단일 합성 금지: 초안 {len(drafts)}개 < 최소 {min_drafts} (§6 '단일 합성 금지')"
        )
    models = [_norm(d.model) for d in drafts]
    if len(set(models)) < len(models):  # 같은 모델 N콜은 독립 초안 아님(리뷰 M3)
        raise GuardViolation(
            f"중복 모델: {sorted(m for m in set(models) if models.count(m) > 1)} — "
            "같은 모델 여러 콜은 독립 초안이 아님(§3 '서로 안 봄')"
        )
    companies = {_norm(d.company) for d in drafts if d.company and d.company.strip()}
    if len(companies) < min_companies:
        raise GuardViolation(
            f"독립 회사 부족: {sorted(companies)} ({len(companies)}) < 최소 {min_companies} "
            "(§2 '독립 학습계보 ≥3' — 같은 회사는 같이 틀린다)"
        )


def assert_judge_separation(
    drafter_models: set[str], judge_models: set[str], *, min_judges: int = 2
) -> None:
    """초안가≠판정기 분리 (§6, A/B 분리 동형): 매칭/판정 모델 ∩ 초안 4모델 = ∅.

    자기 초안을 자기가 cover 판정하면 폐루프 자기 채점이다(§2). 또한 판정기 **≥2** 강제
    (리뷰 C1·C2): 단일/제로 판정기면 '판정 불일치 = 불확실 노출'(§3) 메커니즘이 죽는다.
    비교는 정규화(대소문자·공백)로 — 표기만 바꾼 자기 채점 우회 차단(리뷰 M2).
    """
    js = {_norm(m) for m in judge_models if m and m.strip()}
    if len(js) < min_judges:
        raise GuardViolation(
            f"판정기 부족: {len(js)} < 최소 {min_judges} "
            "(§2/§3 — 판정기 ≥2 라야 불일치를 '불확실'로 노출, 단일이면 메커니즘 사망)"
        )
    ds = {_norm(m) for m in drafter_models if m and m.strip()}
    shared = ds & js
    if shared:
        raise GuardViolation(
            f"초안가≠판정기 분리 위반: 초안 모델과 판정 모델이 겹침 {sorted(shared)} "
            "(§6 — 자기 초안 자기 채점 금지)"
        )


def assert_reflection_completeness(
    merged: MergedProposal, claims: list[Claim], *, majority_support: int
) -> None:
    """반영 추적 = 구조 완전성 (§6):

      1. 모든 **다수 claim**(지지 ≥ majority_support)이 [반영|미반영|추가숙의]로 분류됐다.
      2. 모든 **채택 조항**(REFLECTED/FORCED_MINORITY)이 ≥1 claim id 에 링크됐다
         (반영했다면서 어느 조항도 안 가리키는 빈 채택 금지 — 창작 차단).
    """
    classified = {d.claim.cid for d in merged.decisions}
    majority = {c.cid for c in claims if c.support >= majority_support}
    missing = majority - classified
    if missing:
        raise GuardViolation(
            f"반영 추적 위반: 다수 claim 미분류 {sorted(missing)} "
            "(§6 — 모든 다수 claim은 반영/미반영/추가숙의로 분류돼야)"
        )
    for d in merged.reflected():
        if not d.provenance.clause_ids:
            raise GuardViolation(
                f"반영 추적 위반: 채택 claim {d.claim.cid} 이 어느 조항도 링크 안 함 "
                "(§6 — 채택 조항은 ≥1 claim 링크, 빈 채택은 창작)"
            )
