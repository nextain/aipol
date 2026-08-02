#!/usr/bin/env python3
"""Verify private professor sources without publishing their contents.

The command emits a deterministic hash receipt only. Source text and private
filenames are never written to the repository or stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str]) -> bytes:
    return subprocess.run(command, check=True, capture_output=True).stdout


def normalized(value: bytes) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value.decode("utf-8")))


def require_tokens(label: str, text: str, tokens: list[str]) -> dict[str, bool]:
    result = {token: token in text for token in tokens}
    if not all(result.values()):
        missing = [token for token, present in result.items() if not present]
        raise SystemExit(f"{label} semantic contract mismatch: {missing}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-report", type=Path, required=True)
    parser.add_argument("--prelearning-1", type=Path, required=True)
    parser.add_argument("--prelearning-2", type=Path, required=True)
    parser.add_argument("--steps", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--expected-receipt", type=Path)
    args = parser.parse_args()

    sources = [args.final_report, args.prelearning_1, args.prelearning_2, args.steps]
    if any(not path.is_file() for path in sources):
        raise SystemExit("all four private authority documents are required")
    catalog = json.loads(args.catalog.read_text("utf-8"))
    oracle = json.loads(args.oracle.read_text("utf-8"))
    source_hashes = [digest(path.read_bytes()) for path in sources]
    if source_hashes != oracle["authority_hashes"]:
        raise SystemExit("private authority SHA-256 does not match the approved oracle")
    if source_hashes != catalog["source_contract"]["document_hashes"]:
        raise SystemExit("catalog source binding does not match private authorities")

    hwp_text = [run(["hwp5txt", str(path)]) for path in sources[:3]]
    with tempfile.TemporaryDirectory(prefix="aipol-source-receipt-") as temporary:
        pdf_text_path = Path(temporary) / "steps.txt"
        subprocess.run(
            ["pdftotext", "-layout", str(args.steps), str(pdf_text_path)],
            check=True,
            capture_output=True,
        )
        pdf_text = pdf_text_path.read_bytes()
        info = run(["pdfinfo", str(args.steps)]).decode("utf-8")
        match = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
        if not match:
            raise SystemExit("PDF page count is unavailable")
        page_count = int(match.group(1))
        page_hashes: list[str] = []
        for page in range(1, page_count + 1):
            page_path = Path(temporary) / f"page-{page}.txt"
            subprocess.run(
                ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(args.steps), str(page_path)],
                check=True,
                capture_output=True,
            )
            page_hashes.append(digest(page_path.read_bytes()))

    report_checks = require_tokens(
        "final-report",
        normalized(hwp_text[0]),
        ["65세", "68세", "5.5%", "6%", "0.6%", "100조", "0.25%", "5년"],
    )
    steps_checks = require_tokens(
        "step-by-step",
        normalized(pdf_text),
        [
            "1차", "2차", "3차", "전문가", "개인", "연금", "D안", "D'", "D′", "마무리",
            *oracle["policy_columns"],
        ],
    )
    if catalog["policy_columns"] != oracle["policy_columns"]:
        raise SystemExit("catalog policy-column titles do not match the approved source oracle")
    mapping = catalog["source_contract"]["page_mapping"]
    if set(mapping) != set(oracle["stage_ids"]):
        raise SystemExit("all approved stages require a source-page mapping")
    if any(page < 1 or page > page_count for pages in mapping.values() for page in pages):
        raise SystemExit("source-page mapping points outside the authority PDF")

    receipt = {
        "schema_version": "professor-source-verification-receipt-v1",
        "source_sha256": source_hashes,
        "extracted_text_sha256": [digest(value) for value in [*hwp_text, pdf_text]],
        "pdf_page_count": page_count,
        "pdf_page_text_sha256": page_hashes,
        "stage_page_text_sha256": {
            stage: [page_hashes[page - 1] for page in pages]
            for stage, pages in mapping.items()
        },
        "semantic_check_ids": {
            "final_report_policy_values": sorted(report_checks),
            "step_flow_markers": sorted(steps_checks),
        },
        "catalog_sha256": digest(args.catalog.read_bytes()),
        "oracle_sha256": digest(args.oracle.read_bytes()),
        "extractors": {
            "hwp5txt": run(["hwp5txt", "--version"]).decode("utf-8").strip(),
            "pdftotext": subprocess.run(
                ["pdftotext", "-v"], check=True, capture_output=True, text=True
            ).stderr.splitlines()[0],
        },
    }
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.expected_receipt:
        expected = json.loads(args.expected_receipt.read_text("utf-8"))
        if expected != receipt:
            raise SystemExit("source verification receipt drift detected")
    print(encoded, end="")


if __name__ == "__main__":
    main()
