(function receiptParser(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.AipolReceipt = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function buildParser() {
  "use strict";
  const REQUIRED = ["protected", "payload", "signature"];
  const CONTEXT_FIELDS = [
    "experiment_id", "experiment_version", "session_id", "participant_pseudonym",
    "artifact_id", "artifact_hash", "contract_hash",
  ];
  const CONTRACT_VERSION = "aipol-calculator-return-v2";
  const RETURN_MESSAGE = "aipol.calculator.return";

  function decodeProtected(value) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Invalid protected header.");
    try {
      let text;
      if (typeof Buffer !== "undefined") text = Buffer.from(value, "base64url").toString("utf8");
      else {
        const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
        const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
        text = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
      }
      const header = JSON.parse(text);
      const keys = header && !Array.isArray(header) && typeof header === "object" ? Object.keys(header).sort() : [];
      if (keys.join(",") !== "alg,kid,typ" || header.alg !== "EdDSA" || header.typ !== "JWT" || typeof header.kid !== "string" || !header.kid) throw new Error();
      return header;
    } catch (_) { throw new Error("Protected header does not match the receipt contract."); }
  }

  function validateReceipt(receipt) {
    if (!receipt || Array.isArray(receipt) || typeof receipt !== "object") throw new Error("Receipt must be a JSON object.");
    const keys = Object.keys(receipt).sort();
    if (keys.length !== 3 || !REQUIRED.every((key) => keys.includes(key))) throw new Error("Receipt fields do not match the contract.");
    for (const key of REQUIRED) {
      const limit = key === "signature" ? 256 : 8192;
      if (typeof receipt[key] !== "string" || !receipt[key] || receipt[key].length > limit) throw new Error(`Invalid receipt ${key}.`);
    }
    decodeProtected(receipt.protected);
    return receipt;
  }

  function parse(raw) {
    if (typeof raw !== "string" || !raw.trim() || raw.length > 25000) throw new Error("Invalid signed receipt text.");
    try { return validateReceipt(JSON.parse(raw.trim())); }
    catch (error) { if (error instanceof SyntaxError) throw new Error("Signed receipt is not valid JSON."); throw error; }
  }

  function contextJson(context, maximumBytes) {
    if (!context || Array.isArray(context) || typeof context !== "object") throw new Error("Invalid calculator context.");
    const keys = Object.keys(context).sort();
    if (keys.length !== CONTEXT_FIELDS.length || !CONTEXT_FIELDS.every((key) => keys.includes(key))) throw new Error("Calculator context fields do not match.");
    if (CONTEXT_FIELDS.some((key) => typeof context[key] !== "string" || !context[key])) throw new Error("Calculator context values are invalid.");
    const serialized = JSON.stringify(context);
    const bytes = typeof TextEncoder !== "undefined" ? new TextEncoder().encode(serialized).length : Buffer.byteLength(serialized, "utf8");
    if (bytes > maximumBytes) throw new Error("Calculator context is too large.");
    return serialized;
  }

  function integrationOrigin(integration) {
    if (!integration || integration.contract_version !== CONTRACT_VERSION) throw new Error("Unsupported calculator integration contract.");
    if (!Number.isInteger(integration.max_context_bytes) || integration.max_context_bytes < 256 || integration.max_context_bytes > 8192 || integration.context_fragment_key !== "aipol_context") throw new Error("Invalid calculator context contract.");
    const originUrl = new URL(integration.allowed_origin);
    if (originUrl.protocol !== "https:" || originUrl.username || originUrl.password || originUrl.origin !== integration.allowed_origin || originUrl.pathname !== "/" || originUrl.search || originUrl.hash) throw new Error("Invalid calculator origin.");
    const launch = new URL(integration.launch_url);
    if (launch.protocol !== "https:" || launch.username || launch.password || launch.origin !== originUrl.origin || launch.search || launch.hash || launch.href !== integration.launch_url) throw new Error("Calculator launch URL must be a clean exact-origin URL.");
    let decodedPath;
    try { decodedPath = decodeURIComponent(launch.pathname).toLowerCase(); } catch (_) { throw new Error("Calculator launch path is invalid."); }
    if (/(^|[^a-z0-9])(token|access[-_]?token|api[-_]?key|secret|password|credential|signature|sas)($|[^a-z0-9])/.test(decodedPath)) throw new Error("Calculator launch path resembles embedded credentials.");
    return originUrl.origin;
  }

  function base64url(value) {
    if (typeof Buffer !== "undefined") return Buffer.from(value, "utf8").toString("base64url");
    const bytes = new TextEncoder().encode(value); let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function buildLaunchUrl(integration, context, returnUrl, channelId, siteOrigin) {
    integrationOrigin(integration);
    contextJson(context, integration.max_context_bytes);
    if (typeof channelId !== "string" || !/^[0-9a-f-]{36}$/.test(channelId)) throw new Error("Invalid return channel.");
    const callback = new URL(returnUrl);
    if (callback.origin !== siteOrigin || callback.pathname !== "/aipol-calculator-return.html" || callback.username || callback.password || callback.search || callback.hash || callback.href !== returnUrl) throw new Error("Invalid same-origin return URL.");
    const payload = {contract_version: CONTRACT_VERSION, context, return_url: returnUrl, channel_id: channelId};
    const serialized = JSON.stringify(payload);
    if ((typeof TextEncoder !== "undefined" ? new TextEncoder().encode(serialized).length : Buffer.byteLength(serialized, "utf8")) > integration.max_context_bytes + 1024) throw new Error("Calculator launch context is too large.");
    const launch = new URL(integration.launch_url);
    launch.hash = `${integration.context_fragment_key}=${base64url(serialized)}`;
    return launch.toString();
  }

  function createReturnChannel({channelId, context, BroadcastChannelClass, onReceipt, onStatus}) {
    contextJson(context, 8192);
    if (!BroadcastChannelClass) throw new Error("BroadcastChannel is unsupported.");
    const channel = new BroadcastChannelClass(`aipol-calculator-${channelId}`);
    channel.onmessage = (event) => {
      const message = event.data;
      if (!message || Array.isArray(message) || typeof message !== "object") return;
      if (Object.keys(message).sort().join(",") !== "channel_id,contract_version,experiment_id,receipt,type") return;
      if (message.type !== RETURN_MESSAGE || message.contract_version !== CONTRACT_VERSION || message.channel_id !== channelId || message.experiment_id !== context.experiment_id) return;
      const receipt = validateReceipt(message.receipt);
      if (onReceipt) onReceipt(receipt);
      if (onStatus) onStatus("receipt-received");
    };
    return () => channel.close();
  }

  return {parse, validateReceipt, buildLaunchUrl, createReturnChannel, integrationOrigin, CONTRACT_VERSION, RETURN_MESSAGE};
}));
