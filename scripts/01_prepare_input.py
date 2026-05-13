from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

from common import DATA_DIR, ROOT, elapsed_str, ensure_directories, log_progress, log_step, normalize_url, read_csv_rows, write_csv, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalizza gli URL degli enti da enti.csv")
    parser.add_argument("--input", type=Path, default=ROOT / "enti.csv")
    parser.add_argument("--valid-output", type=Path, default=DATA_DIR / "enti_validi.csv")
    parser.add_argument("--discarded-output", type=Path, default=DATA_DIR / "enti_scartati.csv")
    parser.add_argument("--unique-output", type=Path, default=DATA_DIR / "homepages_unique.csv")
    parser.add_argument("--summary-output", type=Path, default=DATA_DIR / "prepare_input_summary.json")
    parser.add_argument("--progress-every", type=int, default=5000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_directories()

    log_step(f"Loading input CSV from {args.input}")
    rows = read_csv_rows(args.input)
    log_step(f"Loaded {len(rows)} rows from {args.input}")
    t_start = time.monotonic()
    valid_rows: list[dict[str, object]] = []
    discarded_rows: list[dict[str, object]] = []
    grouped_urls: dict[str, list[dict[str, object]]] = defaultdict(list)

    for index, row in enumerate(rows, start=1):
        normalized_url, error = normalize_url(row.get("Sito_istituzionale", ""))
        base = {
            "_id": row.get("_id", ""),
            "Codice_IPA": row.get("Codice_IPA", ""),
            "Denominazione_ente": row.get("Denominazione_ente", ""),
            "Tipologia": row.get("Tipologia", ""),
            "Sito_istituzionale_raw": row.get("Sito_istituzionale", ""),
        }
        if error:
            discarded_rows.append({**base, "discard_reason": error})
            continue
        valid_row = {
            **base,
            "homepage_url": normalized_url,
            "url_key": normalized_url,
        }
        valid_rows.append(valid_row)
        grouped_urls[normalized_url].append(valid_row)
        if args.progress_every > 0 and index % args.progress_every == 0:
            log_progress(
                "prepare-input",
                index,
                len(rows),
                extra=(
                    f"valid={len(valid_rows)} discarded={len(discarded_rows)} "
                    f"unique_homepages={len(grouped_urls)}"
                ),
            )

    unique_rows: list[dict[str, object]] = []
    for homepage_url, members in sorted(grouped_urls.items()):
        first = members[0]
        unique_rows.append(
            {
                "homepage_url": homepage_url,
                "entity_count": len(members),
                "entity_ids": ",".join(str(member["_id"]) for member in members),
                "codici_ipa": ",".join(str(member["Codice_IPA"]) for member in members),
                "sample_denominazione_ente": first["Denominazione_ente"],
                "sample_tipologia": first["Tipologia"],
            }
        )

    write_csv(
        args.valid_output,
        valid_rows,
        [
            "_id",
            "Codice_IPA",
            "Denominazione_ente",
            "Tipologia",
            "Sito_istituzionale_raw",
            "homepage_url",
            "url_key",
        ],
    )
    write_csv(
        args.discarded_output,
        discarded_rows,
        [
            "_id",
            "Codice_IPA",
            "Denominazione_ente",
            "Tipologia",
            "Sito_istituzionale_raw",
            "discard_reason",
        ],
    )
    write_csv(
        args.unique_output,
        unique_rows,
        [
            "homepage_url",
            "entity_count",
            "entity_ids",
            "codici_ipa",
            "sample_denominazione_ente",
            "sample_tipologia",
        ],
    )
    write_json(
        args.summary_output,
        {
            "input_rows": len(rows),
            "valid_entities": len(valid_rows),
            "discarded_entities": len(discarded_rows),
            "unique_homepages": len(unique_rows),
        },
    )
    dupes_collapsed = len(valid_rows) - len(unique_rows)
    log_step(
        f"Prepared {len(valid_rows)} valid entities, {len(discarded_rows)} discarded, "
        f"{len(unique_rows)} unique homepages ({dupes_collapsed} duplicate URLs collapsed)"
    )
    if discarded_rows:
        by_reason = Counter(str(r["discard_reason"]) for r in discarded_rows)
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            log_step(f"  discard reason '{reason}': {count}")
    log_step(f"Wrote {len(valid_rows)} valid entities → {args.valid_output}")
    log_step(f"Wrote {len(discarded_rows)} discarded entities → {args.discarded_output}")
    log_step(f"Wrote {len(unique_rows)} unique homepages → {args.unique_output}")
    log_step(f"Wrote summary → {args.summary_output}")
    log_step(f"Elapsed: {elapsed_str(time.monotonic() - t_start)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
