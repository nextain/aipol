"""Build the global AI-policy watch HTML page and RSS feed from reviewed JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content" / "global-ai-policy"
OUTPUT = ROOT / "site" / "global"
SITE_URL = "https://aipol.kaps.or.kr"
SITE_NAME = "AIPOL"
PAGE_TITLE = "해외 AI 정책개발 동향 | AIPOL"
DESCRIPTION = "정부와 국제기구의 AI 기반 정책개발 동향을 한국어로 요약합니다."
OG_IMAGE = f"{SITE_URL}/assets/og-aipol.png"


def items() -> list[dict[str, str]]:
    result = [json.loads(path.read_text(encoding="utf-8")) for path in CONTENT.glob("*.json")]
    return sorted(result, key=lambda item: (item["published"], item["id"]), reverse=True)


def build_html(records: list[dict[str, str]]) -> str:
    cards = []
    for item in records:
        cards.append(f'''<article class="card" id="{escape(item["id"], quote=True)}"><span class="status-badge status-live">{escape(item["country"])} · {escape(item["published"])}</span><h2>{escape(item["title_ko"])}</h2><p>{escape(item["summary_ko"])}</p><dl class="news-meta"><div><dt>정책개발 활용</dt><dd>{escape(item["policy_use"])}</dd></div><div><dt>사람의 검토</dt><dd>{escape(item["human_review"])}</dd></div><div><dt>AIPOL 시사점</dt><dd>{escape(item["relevance"])}</dd></div><div><dt>한계</dt><dd>{escape(item["caveat"])}</dd></div></dl><p class="source-note">{escape(item["review_status"])} · <a href="{escape(item["source_url"], quote=True)}" rel="noopener">{escape(item["source_name"])} 원문 ↗</a></p></article>''')
    count = len(records)
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"><meta name="description" content="{DESCRIPTION}"><title>{PAGE_TITLE}</title><link rel="canonical" href="{SITE_URL}/global/"><link rel="alternate" hreflang="ko" href="{SITE_URL}/global/"><link rel="alternate" hreflang="en" href="{SITE_URL}/en/global/"><link rel="alternate" hreflang="x-default" href="{SITE_URL}/global/"><meta property="og:type" content="website"><meta property="og:site_name" content="{SITE_NAME}"><meta property="og:title" content="{PAGE_TITLE}"><meta property="og:description" content="{DESCRIPTION}"><meta property="og:url" content="{SITE_URL}/global/"><meta property="og:locale" content="ko_KR"><meta property="og:image" content="{OG_IMAGE}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="AIPOL — KAPS Human + AI Collaboration Policy Lab"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{PAGE_TITLE}"><meta name="twitter:description" content="{DESCRIPTION}"><meta name="twitter:image" content="{OG_IMAGE}"><link rel="stylesheet" href="/assets/site.css"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="icon" href="/assets/favicon.ico" sizes="any"><link rel="apple-touch-icon" href="/assets/apple-touch-icon.png"><link rel="alternate" type="application/rss+xml" title="AIPOL 해외 AI 정책개발 동향" href="/global/rss.xml"><script src="/assets/site.js" defer></script></head>
<body><a class="skip-link" href="#main">본문으로 건너뛰기</a><header class="site-header"><div class="container header-inner"><a class="brand" href="/"><img alt="AIPOL" class="brand-logo" src="/assets/aipol-logo.png"></a><button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav" aria-label="메뉴 열기" data-nav-toggle>메뉴</button><nav class="site-nav" id="site-nav" aria-label="주요 메뉴" data-nav data-open="false"><a href="/project/">소개</a><a href="/method/">활용 방법</a><a href="/cases/">사례</a><a href="/events/">이벤트</a><a href="/participate/">참여</a><a href="/global/" aria-current="page">해외동향</a><a class="lang-switch" href="/en/global/" hreflang="en" lang="en">EN</a></nav></div></header>
<main id="main"><header class="page-hero"><div class="container"><p class="eyebrow">Global AI policy watch</p><h1>해외동향</h1><p class="page-lead">정부·국제기구의 공식 자료에서 AI가 정책 문제 정의, 근거 분석, 의견수렴, 대안 개발과 평가에 쓰이는 사례를 찾아 한국어로 요약합니다.</p><div class="actions"><a class="button button-primary" href="/global/rss.xml">RSS 구독</a><a class="button button-secondary" href="/participate/">동향 제안하기</a></div></div></header><section class="section"><div class="container"><div class="declaration"><div class="declaration-mark" aria-hidden="true">AI</div><div><strong>자동 수집·AI 검토와 공개 승인을 분리합니다.</strong><p>매일 오전 6시에 해외 공식 자료를 수집하고 Solar Pro 4 분석, DeepSeek V4 Pro 검증·교정, GPT-5.6 Luna 번역, DeepSeek V4 Flash 적대검토를 수행합니다. PASS 자료도 자동 공개하지 않으며, 사람이 원문과 공개 문안을 확인한 뒤 Git 검토와 배포를 거쳐 반영합니다. 현재 공개 자료는 {count}건입니다.</p></div></div><div class="news-list">{''.join(cards)}</div></div></section></main>
<footer class="site-footer"><div class="container"><div class="footer-grid"><div><p class="footer-title">Global AI policy watch</p><p>AI 기반 정책개발의 공식 사례와 검증 방법을 한국어로 연결합니다.</p></div><div><h2>Explore</h2><ul><li><a href="/">메인</a></li><li><a href="/cases/">활용 사례</a></li><li><a href="/method/">활용 방법</a></li></ul></div><div><h2>Subscribe</h2><ul><li><a href="/global/rss.xml">RSS</a></li><li><a href="/participate/">동향 제안</a></li></ul></div></div><div class="footer-bottom"><span>현재 {count}건 · 정기 수집·AI 검토 가동 · 사람 승인 후 공개</span><span>검색엔진 공개</span></div></div></footer></body></html>'''


def build_rss(records: list[dict[str, str]]) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "AIPOL 해외 AI 정책개발 동향"), ("link", f"{SITE_URL}/global/"), ("description", "KAPS Human + AI Collaboration Policy Lab(AIPOL)의 정부·국제기구 AI 기반 정책개발 공식 자료 한국어 요약"), ("language", "ko")):
        ET.SubElement(channel, tag).text = value
    for record in records:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = record["title_ko"]
        ET.SubElement(node, "link").text = record["source_url"]
        ET.SubElement(node, "guid", {"isPermaLink": "false"}).text = record["id"]
        ET.SubElement(node, "description").text = f"{record['summary_ko']}\n\nAIPOL 시사점: {record['relevance']}\n한계: {record['caveat']}"
        published = datetime.strptime(record["published"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ET.SubElement(node, "pubDate").text = format_datetime(published, usegmt=True)
    ET.indent(rss)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> None:
    records = items()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "index.html").write_text(build_html(records), encoding="utf-8")
    (OUTPUT / "rss.xml").write_bytes(build_rss(records))
    print(f"built {len(records)} global policy items")


if __name__ == "__main__":
    main()
