"use strict";
(function returnReceipt() {
  const status = document.getElementById("return-status");
  try {
    if (window.opener !== null) throw new Error("This return page must not have an opener.");
    const match = location.hash.match(/^#aipol_return=([A-Za-z0-9_-]+)$/);
    if (!match || match[1].length > 25000) throw new Error("Missing calculator return payload.");
    const padded = match[1].replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - match[1].length % 4) % 4);
    const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
    const value = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
    if (!value || Object.keys(value).sort().join(",") !== "channel_id,contract_version,experiment_id,receipt" || value.contract_version !== AipolReceipt.CONTRACT_VERSION || !/^[0-9a-f-]{36}$/.test(value.channel_id) || typeof value.experiment_id !== "string" || !value.experiment_id) throw new Error("Calculator return contract is invalid.");
    AipolReceipt.validateReceipt(value.receipt);
    const channel = new BroadcastChannel(`aipol-calculator-${value.channel_id}`);
    channel.postMessage({type:AipolReceipt.RETURN_MESSAGE, contract_version:value.contract_version, channel_id:value.channel_id, experiment_id:value.experiment_id, receipt:value.receipt});
    status.textContent = "완료 증명을 원래 행사 화면에 전달했습니다. 이 창을 닫아도 됩니다.";
    setTimeout(() => channel.close(), 1000);
    history.replaceState(null, "", location.pathname);
  } catch (error) {
    status.textContent = `자동 전달에 실패했습니다: ${error.message} 원래 화면에서 서명 영수증을 직접 붙여 넣어 주세요.`;
  }
}());
