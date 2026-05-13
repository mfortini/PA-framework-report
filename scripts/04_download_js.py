from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
from urllib.request import Request, urlopen

from common import JS_FILES_DIR, RESULTS_DIR, append_jsonl, elapsed_str, ensure_directories, eta_str, iter_jsonl, load_processed_values, log_progress, log_step, now_iso, rate_str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scarica i JS e li deduplica per hash")
    parser.add_argument("--input", type=Path, default=RESULTS_DIR / "js_inventory.jsonl")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "js_downloads.jsonl")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    return parser.parse_args()


def download_bytes(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "framework-census/0.1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        content_type = response.headers.get("Content-Type", "")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"response larger than max-bytes={max_bytes}")
        return data, content_type


def looks_like_block_page(payload: bytes, content_type: str) -> bool:
    head = payload[:2048].decode("utf-8", errors="ignore").lower()
    if "text/html" in content_type.lower():
        return True
    html_markers = ("<html", "<!doctype html", "<body", "validation request", "web application firewall", "<title>")
    return any(marker in head for marker in html_markers)


def main() -> int:
    args = parse_args()
    ensure_directories()
    if not args.resume and args.output.exists():
        args.output.unlink()
        log_step(f"Removed existing output because --no-resume is set: {args.output}")
    all_items = [item for item in iter_jsonl(args.input) if item.get("status") == "ok" and item.get("script_url")]
    distinct_urls = len({str(item.get("script_url", "")) for item in all_items})
    log_step(
        f"Loaded {len(all_items)} downloadable JS records from {args.input} "
        f"({distinct_urls} distinct script URLs)"
    )
    items = all_items
    processed = load_processed_values(args.output, "script_url") if args.resume else set()
    if processed:
        log_step(f"Resume enabled: {len(processed)} already downloaded, {distinct_urls - len(processed)} remaining")
    else:
        log_step(f"Starting fresh: {distinct_urls} distinct script URLs to download")
    ok_count = 0
    error_count = 0
    reused_count = 0
    written_count = 0
    total_bytes = 0
    t_start = time.monotonic()

    for index, item in enumerate(items, start=1):
        script_url = str(item.get("script_url", ""))
        if script_url in processed:
            if args.debug:
                log_step(f"resume skip download for {script_url}")
            continue
        record: dict[str, object] = {
            "captured_at": now_iso(),
            "homepage_url": item.get("homepage_url", ""),
            "script_url": script_url,
            "status": "error",
            "content_type": "",
            "sha256": "",
            "saved_path": "",
            "size_bytes": 0,
            "error": "",
        }
        try:
            payload, content_type = download_bytes(script_url, args.timeout, args.max_bytes)
            if looks_like_block_page(payload, content_type):
                raise ValueError("non-javascript response (html/challenge page)")
            sha256 = hashlib.sha256(payload).hexdigest()
            suffix = ".mjs" if script_url.lower().endswith(".mjs") else ".js"
            saved_path = JS_FILES_DIR / f"{sha256}{suffix}"
            if not saved_path.exists():
                saved_path.write_bytes(payload)
            else:
                reused_count += 1
            record.update(
                {
                    "status": "ok",
                    "content_type": content_type,
                    "sha256": sha256,
                    "saved_path": str(saved_path),
                    "size_bytes": len(payload),
                }
            )
            ok_count += 1
            total_bytes += len(payload)
            if args.debug:
                reused_flag = "reused" if saved_path.exists() else "new"
                log_step(f"download ok {script_url}: sha256={sha256[:12]} size={len(payload)} {reused_flag}")
        except Exception as exc:  # noqa: BLE001
            record["error"] = str(exc)
            error_count += 1
            if args.debug:
                log_step(f"download error {script_url}: {exc}")
        append_jsonl(args.output, record)
        processed.add(script_url)
        written_count += 1
        if args.progress_every > 0 and index % args.progress_every == 0:
            elapsed = time.monotonic() - t_start
            mb = total_bytes / 1_048_576
            log_progress(
                "download-js",
                index,
                len(items),
                extra=(
                    f"ok={ok_count} error={error_count} reused={reused_count} "
                    f"written_this_run={written_count} total_processed={len(processed)} "
                    f"downloaded={mb:.1f}MB "
                    f"{rate_str(elapsed, written_count, 'url')} {eta_str(elapsed, written_count, distinct_urls)}"
                ),
            )

    elapsed = time.monotonic() - t_start
    mb = total_bytes / 1_048_576
    reuse_pct = reused_count * 100 // max(ok_count, 1)
    log_step(
        f"Download completed | written_this_run={written_count} ok={ok_count} "
        f"error={error_count} reused={reused_count} ({reuse_pct}% hash-dedup) "
        f"downloaded={mb:.1f}MB total_processed={len(processed)} elapsed={elapsed_str(elapsed)}"
    )
    log_step(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
