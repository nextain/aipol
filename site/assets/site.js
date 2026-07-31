"use strict";

const analyticsMeasurementId = "G-HJDJKV750X";
window.dataLayer = window.dataLayer || [];
window.gtag = window.gtag || function gtag() { window.dataLayer.push(arguments); };
window.gtag("js", new Date());
window.gtag("config", analyticsMeasurementId);

const analyticsScript = document.createElement("script");
analyticsScript.async = true;
analyticsScript.src = `https://www.googletagmanager.com/gtag/js?id=${analyticsMeasurementId}`;
document.head.append(analyticsScript);

const toggle = document.querySelector("[data-nav-toggle]");
const nav = document.querySelector("[data-nav]");
let lastFocused = null;

function focusableInNav() {
  return nav ? [...nav.querySelectorAll('a[href], button:not([disabled])')] : [];
}

function setNav(open) {
  if (!toggle || !nav) return;
  toggle.setAttribute("aria-expanded", String(open));
  const korean = document.documentElement.lang === "ko";
  toggle.setAttribute("aria-label", open ? (korean ? "메뉴 닫기" : "Close menu") : (korean ? "메뉴 열기" : "Open menu"));
  nav.dataset.open = String(open);
  document.body.classList.toggle("nav-open", open);
  if (open) {
    lastFocused = document.activeElement;
    focusableInNav()[0]?.focus();
  } else if (lastFocused) {
    lastFocused.focus();
  }
}

toggle?.addEventListener("click", () => {
  setNav(toggle.getAttribute("aria-expanded") !== "true");
});

document.addEventListener("keydown", (event) => {
  if (!nav || nav.dataset.open !== "true") return;
  if (event.key === "Escape") {
    event.preventDefault();
    setNav(false);
    return;
  }
  if (event.key !== "Tab") return;
  const items = focusableInNav();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

nav?.addEventListener("click", (event) => {
  if (event.target.closest("a") && window.matchMedia("(max-width: 860px)").matches) setNav(false);
});

window.addEventListener("resize", () => {
  if (window.innerWidth > 860 && nav?.dataset.open === "true") setNav(false);
});

document.querySelectorAll("[data-year]").forEach((node) => {
  node.textContent = String(new Date().getFullYear());
});

document.querySelectorAll("[data-print]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});
