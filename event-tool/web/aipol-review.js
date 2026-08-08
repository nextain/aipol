"use strict";

(() => {
  const params = new URLSearchParams(window.location.search);
  const experimentId = params.get("experiment");
  const reviewId = params.get("review");
  const status = document.getElementById("review-handoff-status");
  const link = document.getElementById("review-handoff-link");

  if ((experimentId && reviewId) || (!experimentId && !reviewId)) {
    status.textContent = experimentId && reviewId
      ? "행사와 검토 식별자를 동시에 사용할 수 없습니다. 관리자에게 새 링크를 요청해 주세요."
      : "검토 행사 식별자가 없습니다. 관리자가 발급한 검토 링크를 이용해 주세요.";
    return;
  }

  const mode = reviewId ? "review" : "experiment";
  const eventId = reviewId || experimentId;
  const target = `/aipol.html?${mode}=${encodeURIComponent(eventId)}${window.location.hash}`;
  status.textContent = "동일한 정식 참가자 화면으로 연결합니다.";
  link.href = target;
  link.textContent = "검토 행사 열기";
  window.location.replace(target);
})();
