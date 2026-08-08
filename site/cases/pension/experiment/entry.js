"use strict";

(() => {
  const params = new URLSearchParams(window.location.search);
  const experimentId = params.get("experiment");
  const reviewId = params.get("review");
  const status = document.getElementById("experiment-entry-status");
  const link = document.getElementById("experiment-entry-link");

  if ((experimentId && reviewId) || (!experimentId && !reviewId)) return;

  const mode = reviewId ? "review" : "experiment";
  const eventId = reviewId || experimentId;
  if (!eventId || eventId.length > 160 || /[\u0000-\u001f\u007f]/.test(eventId)) {
    if (status) status.textContent = "행사 링크가 올바르지 않습니다. 진행자에게 새 링크를 요청해 주세요.";
    return;
  }

  let fragment = "";
  if (mode === "review" && window.location.hash) {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("review_token");
    if (!token || !/^S[A-F0-9]{32}$/.test(token)) {
      if (status) status.textContent = "검토 토큰이 올바르지 않습니다. 관리자에게 새 검토 링크를 요청해 주세요.";
      return;
    }
    fragment = `#review_token=${encodeURIComponent(token)}`;
  }

  const target = `https://session.aipol.kaps.or.kr/aipol.html?${mode}=${encodeURIComponent(eventId)}${fragment}`;
  if (status) status.textContent = mode === "review" ? "동일한 정식 서비스의 검토 행사로 연결합니다." : "정식 행사로 연결합니다.";
  if (link) {
    link.href = target;
    link.textContent = mode === "review" ? "검토 행사 열기" : "정식 행사 열기";
  }
  window.location.replace(target);
})();
