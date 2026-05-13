from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from common import (
    RESULTS_DIR,
    elapsed_str,
    ensure_directories,
    eta_str,
    iter_jsonl,
    load_processed_values,
    log_progress,
    log_step,
    maybe_limit_rows,
    now_iso,
    rate_str,
    resolve_obscura_binary,
)


INVENTORY_EVAL = (
    'JSON.stringify((()=>{'
    'const abs=(value)=>{if(!value)return "";try{return new URL(value,location.href).href}catch{return ""}};'
    'const uniq=(items)=>{const seen=new Set();return items.filter((item)=>{const url=item.url||"";if(!url||seen.has(url))return false;seen.add(url);return true;});};'
    'const scripts=uniq(Array.from(document.scripts,(node)=>({url:abs(node.src),source:"dom-script",async:!!node.async,defer:!!node.defer})));'
    'const styles=uniq(Array.from(document.querySelectorAll("link[rel~=stylesheet]"),(node)=>({url:abs(node.href),source:"dom-stylesheet",media:node.media||""})));'
    'const resources=uniq(performance.getEntriesByType("resource").map((entry)=>({url:abs(entry.name),source:"performance-resource",initiatorType:entry.initiatorType||"",transferSize:entry.transferSize||0,encodedBodySize:entry.encodedBodySize||0})));'
    'return {title:document.title||"",finalUrl:location.href,scripts,styles,resources,inlineScriptCount:Array.from(document.scripts).filter((node)=>!node.src).length};'
    '})())'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raccoglie l'inventario dei JS caricati")
    parser.add_argument("--input", type=Path, default=RESULTS_DIR / "homepages.jsonl")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "js_inventory.jsonl")
    parser.add_argument("--css-output", type=Path, default=RESULTS_DIR / "css_inventory.jsonl")
    parser.add_argument("--timeout", type=int, default=30, help="per-page timeout in seconds")
    parser.add_argument("--wait", type=int, default=2, help="extra wait after page load in seconds")
    parser.add_argument("--wait-until", default="load")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--obscura-bin")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel obscura fetch processes")
    parser.add_argument("--stealth", action="store_true")
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    return parser.parse_args()


def looks_like_js(url: str, initiator_type: str = "") -> bool:
    lowered = url.lower()
    if initiator_type == "script":
        return True
    return re.search(r"\.(?:m?js)(?:[?#].*)?$", lowered) is not None


def looks_like_css(url: str, initiator_type: str = "") -> bool:
    lowered = url.lower()
    if initiator_type == "link":
        return True
    return re.search(r"\.css(?:[?#].*)?$", lowered) is not None


class AssetHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.scripts: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): (value or "") for name, value in attrs}
        if tag.lower() == "script":
            src = attrs_dict.get("src", "").strip()
            if src:
                self.scripts.append(urljoin(self.base_url, src))
        elif tag.lower() == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "").strip()
            if href and "stylesheet" in rel:
                self.styles.append(urljoin(self.base_url, href))


def extract_assets_from_saved_html(homepage: dict[str, object]) -> tuple[list[str], list[str]]:
    saved_html_path = str(homepage.get("saved_html_path", "")).strip()
    final_url = str(homepage.get("final_url") or homepage.get("homepage_url") or "")
    if not saved_html_path:
        return [], []
    html_path = Path(saved_html_path)
    if not html_path.exists():
        return [], []
    html_text = html_path.read_text(encoding="utf-8", errors="ignore")
    parser = AssetHTMLParser(final_url)
    parser.feed(html_text)
    return parser.scripts, parser.styles


def run_obscura_inventory(
    obscura_bin: str,
    url: str,
    timeout: int,
    wait: int,
    wait_until: str,
    stealth: bool,
) -> tuple[dict[str, object] | None, str | None]:
    cmd = [
        obscura_bin,
        "fetch",
        url,
        "--quiet",
        "--timeout",
        str(timeout),
        "--wait",
        str(wait),
        "--wait-until",
        wait_until,
        "--eval",
        INVENTORY_EVAL,
    ]
    if stealth:
        cmd.insert(3, "--stealth")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout + wait + 10,
        )
    except subprocess.TimeoutExpired:
        return None, f"subprocess timeout after {timeout + wait + 10}s"
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"obscura exited with {result.returncode}"
        return None, message
    stdout = result.stdout.strip()
    if not stdout:
        return {}, None
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError:
        return None, f"invalid json from obscura: {stdout[:200]}"


def make_empty_js(homepage_url: str, reason: str) -> dict[str, object]:
    return {
        "captured_at": now_iso(),
        "homepage_url": homepage_url,
        "script_url": "",
        "script_hostname": "",
        "resource_type": "",
        "method": "",
        "status": "empty",
        "http_status": None,
        "content_type": "",
        "collection_method": "obscura_fetch_eval",
        "collection_source": "none",
        "failure": "",
        "error": reason,
    }


def make_empty_css(homepage_url: str, reason: str) -> dict[str, object]:
    return {
        "captured_at": now_iso(),
        "homepage_url": homepage_url,
        "css_url": "",
        "css_hostname": "",
        "requested_url": "",
        "final_response_url": "",
        "resource_type": "",
        "method": "",
        "status": "empty",
        "http_status": None,
        "content_type": "",
        "collection_method": "obscura_fetch_eval",
        "collection_source": "none",
        "failure": "",
        "order": None,
        "error": reason,
    }


def build_asset_records(
    homepage: dict[str, object],
    payload: dict[str, object] | None,
    html_scripts: list[str] | None = None,
    html_styles: list[str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    homepage_url = str(homepage["homepage_url"])
    payload = payload or {}
    final_url = str(payload.get("finalUrl") or homepage.get("final_url") or homepage_url)

    js_records: list[dict[str, object]] = []
    css_records: list[dict[str, object]] = []
    seen_js: set[str] = set()
    seen_css: set[str] = set()

    def add_js(url: str, source: str, resource_type: str, extra: dict[str, object] | None = None) -> None:
        if not url or url in seen_js:
            return
        seen_js.add(url)
        js_records.append(
            {
                "captured_at": now_iso(),
                "homepage_url": homepage_url,
                "requested_url": url,
                "script_url": url,
                "script_hostname": urlparse(url).netloc,
                "resource_type": resource_type,
                "method": "GET",
                "status": "ok",
                "http_status": None,
                "content_type": "",
                "collection_method": "obscura_fetch_eval",
                "collection_source": source,
                "failure": "",
                "final_response_url": url,
                **(extra or {}),
            }
        )

    def add_css(url: str, source: str, resource_type: str, extra: dict[str, object] | None = None) -> None:
        if not url or url in seen_css:
            return
        seen_css.add(url)
        css_records.append(
            {
                "captured_at": now_iso(),
                "homepage_url": homepage_url,
                "css_url": url,
                "css_hostname": urlparse(url).netloc,
                "requested_url": url,
                "final_response_url": url,
                "resource_type": resource_type,
                "method": "GET",
                "status": "ok",
                "http_status": None,
                "content_type": "",
                "collection_method": "obscura_fetch_eval",
                "collection_source": source,
                "failure": "",
                **(extra or {}),
            }
        )

    for url in html_scripts or []:
        add_js(url, "saved-html", "script")

    for url in html_styles or []:
        add_css(url, "saved-html", "stylesheet")

    for item in payload.get("scripts", []):
        if isinstance(item, dict):
            add_js(str(item.get("url", "")), str(item.get("source", "dom-script")), "script")

    for item in payload.get("styles", []):
        if isinstance(item, dict):
            add_css(str(item.get("url", "")), str(item.get("source", "dom-stylesheet")), "stylesheet")

    for item in payload.get("resources", []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        initiator_type = str(item.get("initiatorType", ""))
        extra = {
            "transfer_size": item.get("transferSize", 0),
            "encoded_body_size": item.get("encodedBodySize", 0),
        }
        if looks_like_js(url, initiator_type):
            add_js(url, str(item.get("source", "performance-resource")), initiator_type or "script", extra)
        if looks_like_css(url, initiator_type):
            add_css(url, str(item.get("source", "performance-resource")), initiator_type or "stylesheet", extra)

    if not js_records:
        js_records = [make_empty_js(homepage_url, "no javascript assets detected via obscura fetch eval")]
    else:
        for order, record in enumerate(js_records, start=1):
            record["order"] = order
            record["page_final_url"] = final_url

    if not css_records:
        css_records = [make_empty_css(homepage_url, "no css assets detected via obscura fetch eval")]
    else:
        for order, record in enumerate(css_records, start=1):
            record["order"] = order
            record["page_final_url"] = final_url

    return js_records, css_records


def process_homepage(homepage: dict[str, object], args: argparse.Namespace, obscura_bin: str) -> tuple[str, list[dict[str, object]], list[dict[str, object]], str]:
    homepage_url = str(homepage["homepage_url"])
    if homepage.get("status") != "ok":
        return (
            homepage_url,
            [
                {
                    "captured_at": now_iso(),
                    "homepage_url": homepage_url,
                    "script_url": "",
                    "status": "skipped",
                    "collection_method": "obscura_fetch_eval",
                    "collection_source": "homepage-status",
                    "error": f"homepage status is {homepage.get('status')}",
                }
            ],
            [
                {
                    "captured_at": now_iso(),
                    "homepage_url": homepage_url,
                    "css_url": "",
                    "status": "skipped",
                    "collection_method": "obscura_fetch_eval",
                    "collection_source": "homepage-status",
                    "error": f"homepage status is {homepage.get('status')}",
                }
            ],
            "skipped",
        )

    html_scripts, html_styles = extract_assets_from_saved_html(homepage)
    if html_scripts or html_styles:
        js_records, css_records = build_asset_records(
            homepage,
            payload=None,
            html_scripts=html_scripts,
            html_styles=html_styles,
        )
        return homepage_url, js_records, css_records, "ok"

    payload, error = run_obscura_inventory(
        obscura_bin=obscura_bin,
        url=str(homepage.get("final_url") or homepage_url),
        timeout=args.timeout,
        wait=args.wait,
        wait_until=args.wait_until,
        stealth=args.stealth,
    )
    if error:
        return (
            homepage_url,
            [
                {
                    "captured_at": now_iso(),
                    "homepage_url": homepage_url,
                    "script_url": "",
                    "status": "error",
                    "collection_method": "obscura_fetch_eval",
                    "collection_source": "fetch-error",
                    "error": error[:300],
                }
            ],
            [
                {
                    "captured_at": now_iso(),
                    "homepage_url": homepage_url,
                    "css_url": "",
                    "status": "error",
                    "collection_method": "obscura_fetch_eval",
                    "collection_source": "fetch-error",
                    "error": error[:300],
                }
            ],
            "error",
        )

    js_records, css_records = build_asset_records(
        homepage,
        payload=payload or {},
        html_scripts=html_scripts,
        html_styles=html_styles,
    )
    return homepage_url, js_records, css_records, "ok"


def _line(record: dict[str, object]) -> str:
    return json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"


def main() -> int:
    args = parse_args()
    ensure_directories()
    obscura_bin = resolve_obscura_binary(args.obscura_bin)
    if obscura_bin is None:
        raise SystemExit("Obscura binary not found. Set OBSCURA_BIN or run make setup-obscura.")

    if not args.resume:
        for path in (args.output, args.css_output):
            if path.exists():
                path.unlink()
                log_step(f"Removed existing output because --no-resume is set: {path}")

    homepages = maybe_limit_rows(list(iter_jsonl(args.input)), args.limit)
    processed = load_processed_values(args.output, "homepage_url") if args.resume else set()
    pending = [homepage for homepage in homepages if str(homepage["homepage_url"]) not in processed]

    log_step(
        f"Loaded {len(homepages)} homepage records | to process: {len(pending)} | already done: {len(homepages) - len(pending)}"
    )
    log_step(
        f"Starting obscura fetch inventory | concurrency={args.concurrency} timeout={args.timeout}s "
        f"wait={args.wait}s wait_until={args.wait_until}"
    )

    counters = {"ok": 0, "skipped": 0, "errors": 0, "written_js": 0, "written_css": 0}
    completed = 0
    t_start = time.monotonic()

    with args.output.open("a", encoding="utf-8") as js_fh, args.css_output.open("a", encoding="utf-8") as css_fh:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(args.concurrency, 1)) as pool:
            futures = {
                pool.submit(process_homepage, homepage, args, obscura_bin): str(homepage["homepage_url"])
                for homepage in pending
            }
            for future in concurrent.futures.as_completed(futures):
                homepage_url, js_records, css_records, outcome = future.result()
                for record in js_records:
                    js_fh.write(_line(record))
                    counters["written_js"] += 1
                for record in css_records:
                    css_fh.write(_line(record))
                    counters["written_css"] += 1
                js_fh.flush()
                css_fh.flush()
                processed.add(homepage_url)
                counters[f"{outcome if outcome != 'error' else 'errors'}"] += 1
                completed += 1

                if args.debug:
                    ok_js = sum(1 for record in js_records if record.get("status") == "ok")
                    ok_css = sum(1 for record in css_records if record.get("status") == "ok")
                    log_step(f"{outcome} {homepage_url}: js={ok_js} css={ok_css}")

                if args.progress_every > 0 and completed % args.progress_every == 0:
                    elapsed = time.monotonic() - t_start
                    log_progress(
                        "collect-assets",
                        len(processed),
                        len(homepages),
                        extra=(
                            f"ok={counters['ok']} skipped={counters['skipped']} "
                            f"errors={counters['errors']} written_js={counters['written_js']} "
                            f"written_css={counters['written_css']} "
                            f"{rate_str(elapsed, completed, 'pg')} "
                            f"{eta_str(elapsed, completed, len(pending))}"
                        ),
                    )

    elapsed = time.monotonic() - t_start
    total_done = counters["ok"] + counters["skipped"] + counters["errors"]
    ok_pct = counters["ok"] * 100 // max(total_done, 1)
    log_step(
        f"Completed | ok={counters['ok']} ({ok_pct}%) skipped={counters['skipped']} "
        f"errors={counters['errors']} written_js={counters['written_js']} "
        f"written_css={counters['written_css']} elapsed={elapsed_str(elapsed)} "
        f"{rate_str(elapsed, total_done, 'pg')}"
    )
    log_step(f"JS output:  {args.output}")
    log_step(f"CSS output: {args.css_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
