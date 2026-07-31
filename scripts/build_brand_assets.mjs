import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const assets = join(root, "site", "assets");

async function renderSvg(page, sourceName, width, height) {
  const svg = await readFile(join(assets, sourceName), "utf8");
  await page.setViewportSize({ width, height });
  await page.setContent(
    `<style>html,body{margin:0;width:100%;height:100%;overflow:hidden}svg{display:block;width:100%;height:100%}</style>${svg}`,
  );
  return page.screenshot({ type: "png", omitBackground: true });
}

function buildIco(images) {
  const header = Buffer.alloc(6 + images.length * 16);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, png }, index) => {
    const entry = 6 + index * 16;
    header.writeUInt8(size === 256 ? 0 : size, entry);
    header.writeUInt8(size === 256 ? 0 : size, entry + 1);
    header.writeUInt8(0, entry + 2);
    header.writeUInt8(0, entry + 3);
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  return Buffer.concat([header, ...images.map(({ png }) => png)]);
}

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ deviceScaleFactor: 1 });
  const page = await context.newPage();
  const og = await renderSvg(page, "og-aipol.svg", 1200, 630);
  await writeFile(join(assets, "og-aipol.png"), og);
  const apple = await renderSvg(page, "apple-touch-icon.svg", 180, 180);
  await writeFile(join(assets, "apple-touch-icon.png"), apple);
  const icons = [];
  for (const size of [16, 32, 48]) {
    icons.push({ size, png: await renderSvg(page, "favicon.svg", size, size) });
  }
  await writeFile(join(assets, "favicon.ico"), buildIco(icons));
  await context.close();
} finally {
  await browser.close();
}
