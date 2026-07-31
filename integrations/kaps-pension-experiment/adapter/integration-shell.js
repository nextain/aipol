const applyProjectBranding = () => {
  const appTitle = document.querySelector("#main-header h1");
  const appSubtitle = document.querySelector("#main-header h1 + p");
  if (!appTitle || appTitle.dataset.ipolIntegrated === "true") return false;

  appTitle.textContent = "1·2차 국민숙의 시나리오";
  appTitle.dataset.ipolIntegrated = "true";
  if (appSubtitle) appSubtitle.textContent = "PENSION REFORM PROJECT · SCENARIO REVIEW";
  return true;
};

const findOriginalProfileButton = () =>
  [...document.querySelectorAll("button")].find(
    (button) => button.textContent.trim() === "사전 프로필 정보 변경",
  );

const ensureProfileEditButton = () => {
  const controls = document.querySelector("#main-header > div:last-child");
  if (!controls || controls.querySelector(".ipol-profile-edit")) return Boolean(controls);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "ipol-profile-edit";
  button.textContent = "프로필 수정";
  button.setAttribute("aria-label", "사전 프로필 정보 변경");
  button.addEventListener("click", () => findOriginalProfileButton()?.click());
  controls.append(button);
  return true;
};

const ensureLegalFooter = () => {
  const footer = document.querySelector("#content-inner-footer > div");
  if (!footer || footer.dataset.ipolIntegrated === "true") return Boolean(footer);

  footer.classList.add("sm:flex-wrap");
  const operator = document.createElement("p");
  operator.append("공동운영 ");
  for (const [label, href] of [
    ["한국정책학회", "https://kaps.or.kr/"],
    ["넥스테인", "https://about.nextain.io/ko"],
  ]) {
    if (operator.childNodes.length > 1) operator.append(" × ");
    const link = document.createElement("a");
    link.href = href;
    link.textContent = label;
    link.className = "hover:text-blue-600 transition-all";
    operator.append(link);
  }
  footer.insertBefore(operator, footer.lastElementChild);

  const legalLinks = [
    ["이용약관", "/cases/pension/experiment/terms/"],
    ["개인정보처리방침", "/cases/pension/experiment/privacy/"],
  ];
  for (const [label, href] of legalLinks) {
    const placeholder = [...footer.querySelectorAll("span")].find(
      (element) => element.textContent.trim() === label,
    );
    if (!placeholder) continue;
    const link = document.createElement("a");
    link.href = href;
    link.textContent = label;
    link.className = "hover:text-blue-600 transition-all";
    placeholder.replaceWith(link);
  }
  footer.dataset.ipolIntegrated = "true";
  return true;
};

const syncHeaderHeight = () => {
  const header = document.querySelector(".ipol-project-header");
  if (!header) return;
  document.documentElement.style.setProperty(
    "--ipol-header-height",
    `${Math.ceil(header.getBoundingClientRect().height)}px`,
  );
};

applyProjectBranding();
ensureProfileEditButton();
ensureLegalFooter();
syncHeaderHeight();

const observer = new MutationObserver(() => {
  applyProjectBranding();
  ensureProfileEditButton();
  ensureLegalFooter();
});
observer.observe(document.documentElement, { childList: true, subtree: true });

const projectHeader = document.querySelector(".ipol-project-header");
if (projectHeader && "ResizeObserver" in window) {
  new ResizeObserver(syncHeaderHeight).observe(projectHeader);
}
window.addEventListener("resize", syncHeaderHeight);
