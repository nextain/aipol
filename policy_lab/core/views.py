"""[3a]·[3b] 가시화 뷰모델 — 포장이 아니라 이해 (RFC-0003 §1·§6).

가시화의 코드 강제 부분은 **"포장 금지 = 구조 노출"**(§6): 미반영·트레이드오프·리뷰
지적이 통합안과 **동일 데이터 레벨**에 있고, 내용이 있는데 비어있으면 안 된다. 즉 이 뷰모델은
미반영을 **조용히 떨어뜨릴 수 없게** 한다. 수사적 포장(말로 덮기) 판정은 코드 밖 human_gate.

  - [3a] 제시: 통합안 + 미반영 + 추가숙의 + 교차리뷰 지적을 한 구조로(숨길 수 없게).
  - [3b] 반영 경로: 시민별 "내 조건 → 어느 조항(또는 미반영 사유) → 전환/유지".

렌더링(HTML·차트)은 하류다. 여기는 그 입력이 되는 **완전한 뷰모델 + 완전성 가드**다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .guards import GuardViolation
from .synthesis import Disposition, MergedProposal
from .measurement import ArmObservation, Arm


# ── [3a] 제시·숙의 가시화 ───────────────────────────────────────────────


@dataclass(frozen=True)
class ClauseView:
    """통합안 채택 조항 1개 + 근거(어느 claim에서, cover 몇, robust인지)."""

    claim_id: str
    clause_ids: tuple[str, ...]
    cover: int
    robust: bool
    forced_minority: bool   # 소수지만 형평 강제포함


@dataclass(frozen=True)
class ExposureItem:
    """미반영·추가숙의 항목 — 통합안과 **같은 레벨**로 노출(숨길 수 없음)."""

    claim_id: str
    cover: int
    reason: str


@dataclass(frozen=True)
class ReviewNote:
    """교차 적대 리뷰 지적 — 통합안 옆에 그대로."""

    target_model: str
    angle: str
    findings: str


@dataclass
class PresentationView:
    """[3a] 제시 뷰모델 — 채택과 미반영이 한 구조에 공존한다.

    ``adopted`` 만 보여주고 ``unreflected``/``needs_more`` 를 비우는 것이 §6 위반.
    빌더 ``build_presentation`` 가 merge 산출과 대조해 완전성을 강제한다.
    """

    adopted: tuple[ClauseView, ...]
    unreflected: tuple[ExposureItem, ...]
    needs_more: tuple[ExposureItem, ...]
    uncertain: tuple[ExposureItem, ...]      # 판정기 불일치 노출
    reviews: tuple[ReviewNote, ...] = ()


def build_presentation(merged: MergedProposal, reviews=()) -> PresentationView:
    """merge 산출 → 제시 뷰모델. 미반영/추가숙의/불확실을 **누락 없이** 옮긴다(§6)."""
    adopted = tuple(
        ClauseView(
            claim_id=d.claim.cid,
            clause_ids=d.provenance.clause_ids,
            cover=d.cover,
            robust=d.robust,
            forced_minority=(d.disposition == Disposition.FORCED_MINORITY),
        )
        for d in merged.reflected()
    )
    unreflected = tuple(
        ExposureItem(d.claim.cid, d.cover, d.reason) for d in merged.unreflected()
    )
    needs_more = tuple(
        ExposureItem(d.claim.cid, d.cover, d.reason) for d in merged.needs_more()
    )
    uncertain = tuple(
        ExposureItem(d.claim.cid, d.cover, f"판정기 불일치: {', '.join(d.provenance.uncertain_drafts)}")
        for d in merged.uncertain()
    )
    reviews_t = tuple(
        ReviewNote(r.target_model, r.angle, r.findings) for r in reviews
    )
    view = PresentationView(adopted, unreflected, needs_more, uncertain, reviews_t)
    assert_exposure_complete(view, merged)
    return view


def assert_exposure_complete(view: PresentationView, merged: MergedProposal) -> None:
    """포장 금지 = 구조 노출 (§6): merge의 미반영/추가숙의가 뷰에서 누락되면 위반.

    채택만 보이고 미반영을 떨어뜨리는 '말로 덮기'를 데이터 레벨에서 차단한다.
    """
    want_unref = {d.claim.cid for d in merged.unreflected()}
    have_unref = {e.claim_id for e in view.unreflected}
    if want_unref - have_unref:
        raise GuardViolation(
            f"포장 금지 위반: 미반영 claim 누락 {sorted(want_unref - have_unref)} "
            "(§6 — 미반영은 통합안과 동일 레벨로 노출, 떨어뜨리기 금지)"
        )
    want_nm = {d.claim.cid for d in merged.needs_more()}
    have_nm = {e.claim_id for e in view.needs_more}
    if want_nm - have_nm:
        raise GuardViolation(
            f"포장 금지 위반: 추가숙의 claim 누락 {sorted(want_nm - have_nm)} (§6)"
        )
    # 판정기 불일치(불확실)도 RFC §3 '불확실 노출' 약속 — 떨어뜨리기 차단(리뷰 m2)
    want_unc = {d.claim.cid for d in merged.uncertain()}
    have_unc = {e.claim_id for e in view.uncertain}
    if want_unc - have_unc:
        raise GuardViolation(
            f"포장 금지 위반: 불확실(판정기 불일치) claim 누락 {sorted(want_unc - have_unc)} "
            "(§3 — 불확실도 동일 레벨로 노출)"
        )


# ── [3b] 반영·전환 가시화 (개별 추적) ──────────────────────────────────


@dataclass(frozen=True)
class PathStep:
    """시민 한 명의 한 조건 claim → 처분(조항 반영 | 미반영 사유)."""

    claim_id: str
    disposition: str
    clause_ids: tuple[str, ...]    # 반영이면 어느 조항
    reason: str = ""               # 미반영/추가숙의면 사유


@dataclass(frozen=True)
class CitizenPath:
    """[3b] "당신 조건 → 조항/사유 → 전환/유지" 개인별 경로."""

    pid: str
    segment: str
    steps: tuple[PathStep, ...]
    moved: bool                    # 진짜 통합안(①) 제시 후 전환했나


def build_reflection_paths(
    merged: MergedProposal,
    real_arm_obs: list[ArmObservation],
    claim_pids: dict[str, list[str]] | None = None,
) -> list[CitizenPath]:
    """[3b] 시민별 반영 경로 (§1).

    ``claim_pids``: claim id → 그 claim을 제기한 시민 pid들. 생략하면 ``merged`` 안의
    ``Claim.pids`` 에서 자동 유도(리뷰 #5: 손으로 만든 매핑 대신 [2] 추출 산출과 직접 연결).
    ``real_arm_obs``: ① 진짜 통합안 arm 관측(전환 여부). [4] 데이터.
    """
    by_claim = {d.claim.cid: d for d in merged.decisions}
    if claim_pids is None:
        claim_pids = {d.claim.cid: list(d.claim.pids) for d in merged.decisions if d.claim.pids}
    moved_pid = {o.pid: o.moved for o in real_arm_obs if o.arm == Arm.REAL}
    seg_pid = {o.pid: o.segment for o in real_arm_obs if o.arm == Arm.REAL}

    # pid → 그가 제기한 claim들
    pid_claims: dict[str, list[str]] = {}
    for cid, pids in claim_pids.items():
        for p in pids:
            pid_claims.setdefault(p, []).append(cid)

    paths: list[CitizenPath] = []
    for pid in sorted(pid_claims):
        steps = []
        for cid in pid_claims[pid]:
            d = by_claim.get(cid)
            if d is None:
                continue
            steps.append(
                PathStep(
                    claim_id=cid,
                    disposition=d.disposition.value,
                    clause_ids=d.provenance.clause_ids,
                    reason=d.reason,
                )
            )
        paths.append(
            CitizenPath(
                pid=pid,
                segment=seg_pid.get(pid, ""),
                steps=tuple(steps),
                moved=moved_pid.get(pid, False),
            )
        )
    return paths
