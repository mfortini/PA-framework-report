from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path

from common import (
    DATA_DIR,
    RESULTS_DIR,
    append_jsonl,
    elapsed_str,
    ensure_directories,
    eta_str,
    html_snapshot_path,
    load_processed_values,
    log_progress,
    log_step,
    maybe_limit_rows,
    now_iso,
    rate_str,
    resolve_obscura_binary,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visita le homepage e raccoglie metadati iniziali")
    parser.add_argument("--input", type=Path, default=DATA_DIR / "homepages_unique.csv")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "homepages.jsonl")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--wait-until", default="domcontentloaded")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--obscura-bin")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    return parser.parse_args()


def run_obscura(
    obscura_bin: str,
    url: str,
    timeout: int,
    wait_until: str,
) -> tuple[dict[str, object] | None, str | None]:
    cmd = [
        obscura_bin,
        "fetch",
        url,
        "--quiet",
        "--timeout",
        str(timeout),
        "--wait-until",
        wait_until,
        "--eval",
        "JSON.stringify({title: document.title, finalUrl: location.href, html: document.documentElement.outerHTML})",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired:
        return None, f"subprocess timeout after {timeout + 10}s"
    if result.returncode != 0:
        return None, result.stderr.strip() or f"obscura exited with {result.returncode}"
    stdout = result.stdout.strip()
    if not stdout:
        return {}, None
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError:
        return {"raw_output": stdout}, None


def main() -> int:
    args = parse_args()
    ensure_directories()
    obscura_bin = resolve_obscura_binary(args.obscura_bin)
    if obscura_bin is None:
        raise SystemExit("Obscura binary not found. Set OBSCURA_BIN or run make setup-obscura.")
    log_step(f"Using Obscura binary: {obscura_bin}")
    if not args.resume and args.output.exists():
        args.output.unlink()
        log_step(f"Removed existing output because --no-resume is set: {args.output}")

    with args.input.open("r", encoding="utf-8", newline="") as handle:
        rows = maybe_limit_rows(list(csv.DictReader(handle)), args.limit)
    log_step(f"Loaded {len(rows)} homepage rows from {args.input}")
    processed = load_processed_values(args.output, "homepage_url") if args.resume else set()
    if processed:
        log_step(f"Resume enabled: {len(processed)} already done, {len(rows) - len(processed)} remaining")
    else:
        log_step(f"Starting fresh: {len(rows)} homepages to probe")

    records_written = 0
    ok_count = 0
    error_count = 0
    t_start = time.monotonic()
    for index, row in enumerate(rows, start=1):
        homepage_url = row["homepage_url"]
        if homepage_url in processed:
            if args.debug:
                log_step(f"resume skip for {homepage_url}")
            continue
        if index <= 3 or args.debug or (args.progress_every > 0 and (index == 1 or index % args.progress_every == 0)):
            log_step(f"starting probe {index}/{len(rows)} for {homepage_url}")
        record: dict[str, object] = {
            "captured_at": now_iso(),
            "homepage_url": homepage_url,
            "entity_count": row.get("entity_count", ""),
            "entity_ids": row.get("entity_ids", ""),
            "status": "error",
            "engine": "obscura",
            "requested_url": homepage_url,
            "final_url": homepage_url,
            "title": "",
            "error": "",
            "saved_html_path": "",
            "html_size_bytes": 0,
        }
        payload, error = run_obscura(obscura_bin, homepage_url, args.timeout, args.wait_until)
        if error:
            record["error"] = error
            error_count += 1
            if args.debug:
                log_step(f"probe error for {homepage_url}: {error}")
        else:
            record["status"] = "ok"
            ok_count += 1
            record["title"] = str((payload or {}).get("title", ""))
            record["final_url"] = str((payload or {}).get("finalUrl", homepage_url))
            html = str((payload or {}).get("html", ""))
            if html:
                html_path = html_snapshot_path(homepage_url)
                html_path.write_text(html, encoding="utf-8")
                record["saved_html_path"] = str(html_path)
                record["html_size_bytes"] = len(html.encode("utf-8"))
            if "raw_output" in (payload or {}):
                record["raw_output"] = payload["raw_output"]
            if args.debug:
                log_step(
                    f"probe ok for {homepage_url}: final_url={record['final_url']} "
                    f"title={record['title'][:80]}"
                )
        append_jsonl(args.output, record)
        processed.add(homepage_url)
        records_written += 1
        if args.progress_every > 0 and index % args.progress_every == 0:
            elapsed = time.monotonic() - t_start
            log_progress(
                "probe-homepages",
                index,
                len(rows),
                extra=(
                    f"ok={ok_count} error={error_count} written_this_run={records_written} "
                    f"total_processed={len(processed)} "
                    f"{rate_str(elapsed, records_written, 'url')} {eta_str(elapsed, records_written, len(rows))}"
                ),
            )

    elapsed = time.monotonic() - t_start
    ok_pct = ok_count * 100 // max(records_written, 1)
    log_step(
        f"Probe completed | written_this_run={records_written} ok={ok_count} ({ok_pct}%) "
        f"error={error_count} total_processed={len(processed)} elapsed={elapsed_str(elapsed)}"
    )
    log_step(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
