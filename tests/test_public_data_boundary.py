from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_internal_run_artifacts_are_not_part_of_the_public_tree() -> None:
    assert "instances/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert not any((ROOT / "instances").rglob("*"))
    assert not any((ROOT / "docs" / "reviews").rglob("*"))
    assert not any(path.is_file() for path in (ROOT / "site" / "cases" / "pension" / "report").rglob("*"))
    assert not any(path.is_file() for path in (ROOT / "site" / "en" / "cases" / "pension" / "report").rglob("*"))
    assert not (ROOT / "event-tool" / "sim_threads.json").exists()
    assert not any(path.is_file() for path in (ROOT / "event-tool" / "instances").rglob("*"))
    assert not (ROOT / "event-tool" / "make_static.py").exists()


def test_known_unpublished_material_markers_are_absent_from_public_content() -> None:
    roots = [ROOT]
    text_parts: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if ".git" in path.parts or ".venv" in path.parts:
                continue
            if path.is_file() and path.suffix.lower() in {
                ".html", ".json", ".md", ".py", ".txt", ".xml", ".yaml", ".yml"
            }:
                text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
    public_text = "\n".join(text_parts)
    forbidden = (
        "부분적립형 확정급여" + "(양재진 안)",
        "2026~2027년 2년간 " + "100조원",
        "사전등록 연령 " + "배분",
        "Upstage Solar Open2 " + "크레딧 문의 초안",
        "루크·" + "홍아름 교수님",
        "루크 " + "승인",
        "루크 " + "지시",
        "통화 " + "결정 기반",
        "pension-rehearsal-" + "2026",
        "pension-runner-100-" + "2026",
        "홍아름 교수 " + "제공 PR",
    )
    for marker in forbidden:
        assert marker not in public_text
