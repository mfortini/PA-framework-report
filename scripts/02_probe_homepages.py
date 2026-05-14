from __future__ import annotations

import argparse
import csv
import json
import re
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
    iter_jsonl,
    load_processed_values,
    log_progress,
    log_step,
    maybe_limit_rows,
    now_iso,
    rate_str,
    resolve_obscura_binary,
    write_jsonl,
)

HEADER_CAPTURE_KEYS = (
    "server",
    "x-powered-by",
    "x-aspnet-version",
    "x-aspnetmvc-version",
    "x-generator",
    "via",
)
HEADER_USER_AGENT = "FrameworkDetector/1.0 (+https://example.invalid)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visita le homepage e raccoglie metadati iniziali")
    parser.add_argument("--input", type=Path, default=DATA_DIR / "homepages_unique.csv")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "homepages.jsonl")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--header-timeout", type=int, default=12)
    parser.add_argument("--wait-until", default="domcontentloaded")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--obscura-bin")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--headers-only", action="store_true")
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


def extract_cookie_names(raw_headers: list[str]) -> list[str]:
    names = set()
    for raw_header in raw_headers:
        cookie_name = raw_header.split(";", 1)[0].split("=", 1)[0].strip()
        if cookie_name:
            names.add(cookie_name)
    return sorted(names)


def fetch_response_headers(url: str, timeout: int) -> tuple[dict[str, object], str | None]:
    cmd = [
        "curl",
        "-sS",
        "-D",
        "-",
        "-o",
        "/dev/null",
        "-L",
        "--max-time",
        str(timeout),
        "-A",
        HEADER_USER_AGENT,
        url,
        "-w",
        "\nCURL_EFFECTIVE_URL:%{url_effective}\nCURL_RESPONSE_CODE:%{response_code}\n",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            {
                "header_probe_status": "error",
                "header_probe_url": url,
                "response_headers": {},
                "set_cookie_names": [],
                "header_probe_error": f"curl timeout after {timeout + 5}s",
            },
            str(exc),
        )

    if result.returncode != 0:
        stderr_text = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        error_message = stderr_text or f"curl exited with {result.returncode}"
        return (
            {
                "header_probe_status": "error",
                "header_probe_url": url,
                "response_headers": {},
                "set_cookie_names": [],
                "header_probe_error": error_message,
            },
            error_message,
        )

    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    effective_url_match = re.search(r"CURL_EFFECTIVE_URL:(.+)", stdout)
    response_code_match = re.search(r"CURL_RESPONSE_CODE:(\d+)", stdout)
    effective_url = effective_url_match.group(1).strip() if effective_url_match else url
    response_code = int(response_code_match.group(1)) if response_code_match else 0
    header_blob = re.sub(r"\nCURL_EFFECTIVE_URL:.*", "", stdout, flags=re.DOTALL).strip()
    header_blocks = [block.strip() for block in re.split(r"\r?\n\r?\n", header_blob) if block.strip()]
    last_header_block = header_blocks[-1] if header_blocks else ""

    selected_headers: dict[str, str] = {}
    raw_cookie_headers: list[str] = []
    for line in last_header_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        lowered = key.strip().lower()
        cleaned_value = value.strip()
        if lowered in HEADER_CAPTURE_KEYS:
            selected_headers[lowered] = cleaned_value
        if lowered == "set-cookie":
            raw_cookie_headers.append(cleaned_value)

    header_status = "ok"
    header_error = ""
    if response_code >= 400:
        header_status = "http-error"
        header_error = f"http {response_code}"

    return (
        {
            "header_probe_status": header_status,
            "header_probe_url": effective_url,
            "response_headers": selected_headers,
            "set_cookie_names": extract_cookie_names(raw_cookie_headers),
            "header_probe_error": header_error,
        },
        None if not header_error else header_error,
    )


def enrich_existing_headers(args: argparse.Namespace) -> int:
    records = list(iter_jsonl(args.output))
    if not records:
        raise SystemExit(f"No homepage records found in {args.output}; run the probe first.")
    log_step(f"Loaded {len(records)} existing homepage records from {args.output}")
    target_count = min(len(records), args.limit) if args.limit and args.limit > 0 else len(records)
    updated_records: list[dict[str, object]] = []
    processed_count = 0
    skipped_count = 0
    t_start = time.monotonic()

    for index, record in enumerate(records, start=1):
        if index > target_count:
            updated_records.extend(records[index - 1 :])
            break
        if str(record.get("status", "")) != "ok":
            updated_records.append(record)
            skipped_count += 1
            continue
        if args.resume and record.get("header_probe_status") == "ok":
            updated_records.append(record)
            skipped_count += 1
            continue

        target_url = str(record.get("final_url") or record.get("requested_url") or record.get("homepage_url") or "")
        header_payload, header_error = fetch_response_headers(target_url, args.header_timeout)
        record.update(header_payload)
        if args.debug and header_error:
            log_step(f"header enrichment error for {target_url}: {header_error}")
        updated_records.append(record)
        processed_count += 1

        if args.progress_every > 0 and index % args.progress_every == 0:
            elapsed = time.monotonic() - t_start
            log_progress(
                "probe-homepage-headers",
                index,
                target_count,
                extra=f"updated={processed_count} skipped={skipped_count} {rate_str(elapsed, processed_count, 'url')}",
            )

    write_jsonl(args.output, updated_records)
    elapsed = time.monotonic() - t_start
    log_step(
        f"Header enrichment completed | updated={processed_count} skipped={skipped_count} "
        f"elapsed={elapsed_str(elapsed)} output={args.output}"
    )
    return 0


def main() -> int:
    args = parse_args()
    ensure_directories()
    if args.headers_only:
        return enrich_existing_headers(args)

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
            "header_probe_status": "",
            "header_probe_url": homepage_url,
            "header_probe_error": "",
            "response_headers": {},
            "set_cookie_names": [],
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
            header_payload, header_error = fetch_response_headers(str(record["final_url"]), args.header_timeout)
            record.update(header_payload)
            if args.debug and header_error:
                log_step(f"header probe error for {homepage_url}: {header_error}")
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
