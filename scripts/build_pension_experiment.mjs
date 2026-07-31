import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const integration = join(root, "integrations", "kaps-pension-experiment");
const vendor = join(integration, "vendor");
const adapter = join(integration, "adapter");
const output = join(root, "site", "cases", "pension", "experiment");
const vite = join(vendor, "node_modules", "vite", "bin", "vite.js");
const projectTitle = "연금개혁-AI 숙의민주주의 정책실험";

execFileSync(
  process.execPath,
  [
    vite,
    "build",
    "--base=/cases/pension/experiment/",
    `--outDir=${output}`,
    "--emptyOutDir",
  ],
  { cwd: vendor, stdio: "inherit" },
);

const indexPath = join(output, "index.html");
let html = readFileSync(indexPath, "utf8")
  .replace('<html lang="en">', '<html lang="ko">')
  .replace("<title>My Google AI Studio App</title>", `<title>${projectTitle} | AIPOL</title>`)
  .replace(
    "</head>",
    `  <meta name="description" content="AIPOL ${projectTitle}의 1·2차 국민숙의 시나리오 검토 화면입니다." />
    <meta name="robots" content="noindex,nofollow,noarchive" />
    <meta name="aipol-source-commit" content="fcbae3c0dab18476e2274f9e4ff91dadeb2db944" />
    <link rel="canonical" href="https://aipol.kaps.or.kr/cases/pension/experiment/" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="AIPOL" />
    <meta property="og:title" content="${projectTitle} | AIPOL" />
    <meta property="og:description" content="AIPOL ${projectTitle}의 1·2차 국민숙의 시나리오 검토 화면입니다." />
    <meta property="og:url" content="https://aipol.kaps.or.kr/cases/pension/experiment/" />
    <meta property="og:image" content="https://aipol.kaps.or.kr/assets/og-aipol.png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${projectTitle} | AIPOL" />
    <meta name="twitter:description" content="AIPOL ${projectTitle}의 1·2차 국민숙의 시나리오 검토 화면입니다." />
    <meta name="twitter:image" content="https://aipol.kaps.or.kr/assets/og-aipol.png" />
    <link rel="stylesheet" href="/assets/site.css" />
    <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml" />
    <script defer src="/assets/site.js"></script>
    <link rel="stylesheet" href="/cases/pension/experiment/integration-shell.css" />
  </head>`,
  )
  .replace(
    "<body>",
    `<body>
    <header class="ipol-project-header">
      <a class="ipol-project-brand" href="/" aria-label="AIPOL 홈">
        <img src="/assets/aipol-logo.png" alt="AIPOL" />
      </a>
      <div class="ipol-project-title">
        <span>AIPOL PROJECT 01</span>
        <strong>${projectTitle}</strong>
      </div>
      <nav aria-label="${projectTitle}">
        <a href="/cases/pension/">프로젝트 소개</a>
        <a href="/cases/pension/#scenario-review">연금팀 검토 기준</a>
      </nav>
    </header>`,
  )
  .replace("</body>", '    <script src="/cases/pension/experiment/integration-shell.js" defer></script>\n  </body>');
html = `${html.replace(/\r\n?/g, "\n").trimEnd()}\n`;
writeFileSync(indexPath, html, "utf8");

copyFileSync(join(adapter, "integration-shell.css"), join(output, "integration-shell.css"));
copyFileSync(join(adapter, "integration-shell.js"), join(output, "integration-shell.js"));
for (const page of ["terms", "privacy"]) {
  const destination = join(output, page);
  mkdirSync(destination, { recursive: true });
  copyFileSync(join(adapter, `${page}.html`), join(destination, "index.html"));
}

writeFileSync(
  join(output, "provenance.json"),
  `${JSON.stringify(
    {
      platform: "AIPOL",
      project: projectTitle,
      source_repository: "https://github.com/armybonita/2026-Flagship-Session-KAPS-Human-AI-Collaborative-Policy-Lab-/",
      source_pull_request: 1,
      source_commit: "fcbae3c0dab18476e2274f9e4ff91dadeb2db944",
      source_scope: "top-level scenario app; personal-pension-simulator subproject excluded",
      integration_route: "/cases/pension/experiment/",
      measurement_flow: "first vote -> AI diagnosis and small-group discussion -> second final vote",
      review_audience: "pension team",
    },
    null,
    2,
  )}\n`,
  "utf8",
);
