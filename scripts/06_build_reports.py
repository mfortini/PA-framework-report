from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import RESULTS_DIR, ensure_directories, iter_jsonl, log_step, write_csv, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Costruisce i report finali")
    parser.add_argument("--input", type=Path, default=RESULTS_DIR / "framework_detection.jsonl")
    parser.add_argument("--summary-output", type=Path, default=RESULTS_DIR / "summary.csv")
    parser.add_argument("--aggregate-output", type=Path, default=RESULTS_DIR / "framework_summary.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_directories()
    records = list(iter_jsonl(args.input))
    log_step(f"Building reports from {len(records)} detection records in {args.input}")

    write_csv(
        args.summary_output,
        (
            {
                "_id": record.get("_id", ""),
                "Codice_IPA": record.get("Codice_IPA", ""),
                "Denominazione_ente": record.get("Denominazione_ente", ""),
                "Tipologia": record.get("Tipologia", ""),
                "homepage_url": record.get("homepage_url", ""),
                "homepage_status": record.get("homepage_status", ""),
                "framework_primario": record.get("framework_primario", ""),
                "framework_secondari": ",".join(record.get("framework_secondari", [])),
                "cms_primario": record.get("cms_primario", ""),
                "ui_frameworks": ",".join(record.get("ui_frameworks", [])),
                "confidence": record.get("confidence", ""),
                "js_count": record.get("js_count", 0),
                "css_count": record.get("css_count", 0),
                "evidenze_count": len(record.get("evidenze", [])),
            }
            for record in records
        ),
        [
            "_id",
            "Codice_IPA",
            "Denominazione_ente",
            "Tipologia",
            "homepage_url",
            "homepage_status",
            "framework_primario",
            "framework_secondari",
            "cms_primario",
            "ui_frameworks",
            "confidence",
            "js_count",
            "css_count",
            "evidenze_count",
        ],
    )

    counter = Counter(record.get("framework_primario", "") for record in records if record.get("framework_primario"))
    secondary_counter = Counter(
        framework
        for record in records
        for framework in record.get("framework_secondari", [])
        if framework
    )
    cms_counter = Counter(record.get("cms_primario", "") for record in records if record.get("cms_primario"))
    ui_counter = Counter(
        framework
        for record in records
        for framework in record.get("ui_frameworks", [])
        if framework
    )
    write_json(
        args.aggregate_output,
        {
            "entities_total": len(records),
            "framework_counts": dict(counter.most_common()),
            "secondary_framework_counts": dict(secondary_counter.most_common()),
            "cms_counts": dict(cms_counter.most_common()),
            "ui_framework_counts": dict(ui_counter.most_common()),
        },
    )
    detected = sum(1 for r in records if r.get("framework_primario") or r.get("cms_primario"))
    high_conf = sum(1 for r in records if r.get("confidence") == "high")
    log_step(
        f"Wrote {args.summary_output} and {args.aggregate_output} | "
        f"entities={len(records)} detected={detected} high_confidence={high_conf}"
    )
    log_step("Top frameworks (primary):")
    for name, count in counter.most_common(8):
        pct = count * 100 // max(len(records), 1)
        log_step(f"  {name}: {count} ({pct}%)")
    if secondary_counter:
        log_step("Top frameworks (secondary):")
        for name, count in secondary_counter.most_common(8):
            pct = count * 100 // max(len(records), 1)
            log_step(f"  {name}: {count} ({pct}%)")
    if cms_counter:
        log_step("Top CMS:")
        for name, count in cms_counter.most_common(5):
            pct = count * 100 // max(len(records), 1)
            log_step(f"  {name}: {count} ({pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
