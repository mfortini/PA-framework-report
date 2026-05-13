from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

from common import DATA_DIR, RESULTS_DIR, elapsed_str, ensure_directories, iter_jsonl, log_progress, log_step, rate_str, read_csv_rows, write_jsonl


URL_RULES = {
    "WordPress": ("wp-content", "wp-includes", "elementor", "woocommerce"),
    "Next.js": ("/_next/", "__next"),
    "Nuxt": ("/_nuxt/", "__NUXT__", "window.__NUXT__"),
    "Drupal": ("drupal", "drupalSettings", "sites/default/files/js"),
    "Joomla": ("joomla",),
    "Liferay": ("/o/", "__liferay__", "Liferay.Loader", "themeDisplay"),
    "Blazor": ("/_framework/", "blazor"),
    "Angular": ("ng-version",),
    "Vue": ("data-v-",),
    "Bootstrap Italia": ("bootstrap-italia", "bootstrap_italia"),
}

CMS_RULES = {
    "WordPress": ("wp-content", "wp-includes", "wp-json", "elementor", "woocommerce"),
    "Drupal": ("drupal", "drupalSettings", "sites/default/files"),
    "Joomla": ("joomla",),
    "Liferay": ("/o/", "__liferay__", "Liferay.Loader", "themeDisplay"),
}

CONTENT_RULES = {
    "React": ("React", "react.production", "createElement"),
    "Vue": ("Vue", "__VUE__", "createApp("),
    "Angular": ("zone.js", "ng-version", "@angular"),
    "jQuery": ("jQuery", "$.fn.jquery"),
    "Bootstrap": ("bootstrap", "data-bs-toggle"),
    "Bootstrap Italia": ("bootstrap-italia", "--bootstrap-italia-version", "bootstrapitalia"),
    "Liferay": ("Liferay.Loader", "Liferay.ThemeDisplay", "Liferay.Portlet", "themeDisplay", "@liferay/"),
    "Alpine.js": ("Alpine", "x-data"),
    "Svelte": ("SvelteComponent",),
    "Stimulus": ("stimulus", "data-controller"),
}

HTML_RULES = {
    "Next.js": ('id="__next"', "__NEXT_DATA__"),
    "Nuxt": ("__NUXT__", 'id="__nuxt"'),
    "Angular": ("ng-version",),
    "Vue": ("data-v-", 'id="app"'),
    "Bootstrap Italia": ("bootstrap-italia", "bootstrap_italia", "--bootstrap-italia-version"),
    "WordPress": ("wp-content", "wp-includes", "wp-json", "wordpress"),
    "Drupal": ("drupalSettings",),
    "Joomla": ("joomla",),
    "Liferay": ("Liferay.ThemeDisplay", "themeDisplay", "__liferay__", "Liferay.Loader"),
    "Blazor": ("/_framework/blazor", "blazor-error-ui"),
}

CSS_URL_RULES = {
    "Bootstrap": ("bootstrap",),
    "Bootstrap Italia": ("bootstrap-italia", "bootstrap_italia"),
    "Tailwind CSS": ("tailwind",),
    "Bulma": ("bulma",),
    "Foundation": ("foundation",),
    "UIkit": ("uikit",),
    "Materialize": ("materialize",),
    "Elementor": ("elementor",),
}


def prefer_bootstrap_italia(framework_hits: dict[str, list[str]], ui_hits: dict[str, list[str]]) -> None:
    # Bootstrap Italia bundles include Bootstrap internally, so keep the specific label when present.
    if framework_hits.get("Bootstrap Italia"):
        framework_hits.pop("Bootstrap", None)
    if ui_hits.get("Bootstrap Italia"):
        ui_hits.pop("Bootstrap", None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inferisce framework e CMS da URL, HTML e JS")
    parser.add_argument("--entities-input", type=Path, default=DATA_DIR / "enti_validi.csv")
    parser.add_argument("--homepages-input", type=Path, default=RESULTS_DIR / "homepages.jsonl")
    parser.add_argument("--inventory-input", type=Path, default=RESULTS_DIR / "js_inventory.jsonl")
    parser.add_argument("--css-inventory-input", type=Path, default=RESULTS_DIR / "css_inventory.jsonl")
    parser.add_argument("--downloads-input", type=Path, default=RESULTS_DIR / "js_downloads.jsonl")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "framework_detection.jsonl")
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def detect_from_text(framework_hits: dict[str, list[str]], text: str, source: str, rules: dict[str, tuple[str, ...]]) -> None:
    lowered = text.lower()
    for framework, markers in rules.items():
        for marker in markers:
            if marker.lower() in lowered:
                framework_hits[framework].append(f"{source}:{marker}")


def main() -> int:
    args = parse_args()
    ensure_directories()

    homepage_records = {str(record.get("homepage_url", "")): record for record in iter_jsonl(args.homepages_input)}
    log_step(f"Loaded {len(homepage_records)} homepage records from {args.homepages_input}")
    entities = [
        entity
        for entity in read_csv_rows(args.entities_input)
        if entity.get("homepage_url", "") in homepage_records
    ]
    log_step(f"Loaded {len(entities)} entities intersecting with homepage results")
    inventory_by_homepage: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in iter_jsonl(args.inventory_input):
        inventory_by_homepage[str(record.get("homepage_url", ""))].append(record)
    log_step(
        f"Loaded JS inventory: {sum(len(v) for v in inventory_by_homepage.values())} records "
        f"across {len(inventory_by_homepage)} homepages from {args.inventory_input}"
    )
    css_by_homepage: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in iter_jsonl(args.css_inventory_input):
        css_by_homepage[str(record.get("homepage_url", ""))].append(record)
    log_step(
        f"Loaded CSS inventory: {sum(len(v) for v in css_by_homepage.values())} records "
        f"across {len(css_by_homepage)} homepages from {args.css_inventory_input}"
    )
    downloads_by_url: dict[str, dict[str, object]] = {}
    for record in iter_jsonl(args.downloads_input):
        downloads_by_url[str(record.get("script_url", ""))] = record
    log_step(f"Loaded {len(downloads_by_url)} downloaded JS entries from {args.downloads_input}")
    t_start = time.monotonic()

    detections: list[dict[str, object]] = []
    detected_count = 0
    for index, entity in enumerate(entities, start=1):
        homepage_url = entity["homepage_url"]
        framework_hits: dict[str, list[str]] = defaultdict(list)
        cms_hits: dict[str, list[str]] = defaultdict(list)
        ui_hits: dict[str, list[str]] = defaultdict(list)
        homepage_record = homepage_records.get(homepage_url, {})
        saved_html = str(homepage_record.get("saved_html_path", "")) if homepage_record else ""
        html_path = Path(saved_html) if saved_html else None
        if html_path and html_path.exists():
            html_text = html_path.read_text(encoding="utf-8", errors="ignore")[:200_000]
            detect_from_text(framework_hits, html_text, f"html:{html_path.name}", HTML_RULES)
            detect_from_text(cms_hits, html_text, f"html:{html_path.name}", CMS_RULES)
        for item in inventory_by_homepage.get(homepage_url, []):
            script_url = str(item.get("script_url", ""))
            detect_from_text(framework_hits, script_url, "url", URL_RULES)
            detect_from_text(cms_hits, script_url, "url", CMS_RULES)
            download = downloads_by_url.get(script_url)
            if download and download.get("status") == "ok":
                saved_path = Path(str(download["saved_path"]))
                if saved_path.exists():
                    detect_from_text(
                        framework_hits,
                        saved_path.read_text(encoding="utf-8", errors="ignore")[:200_000],
                        f"content:{saved_path.name}",
                        CONTENT_RULES,
                    )
        for item in css_by_homepage.get(homepage_url, []):
            css_url = str(item.get("css_url", ""))
            detect_from_text(cms_hits, css_url, "css-url", CMS_RULES)
            detect_from_text(ui_hits, css_url, "css-url", CSS_URL_RULES)

        prefer_bootstrap_italia(framework_hits, ui_hits)

        ordered = sorted(framework_hits.items(), key=lambda item: (-len(item[1]), item[0]))
        cms_ordered = sorted(cms_hits.items(), key=lambda item: (-len(item[1]), item[0]))
        ui_ordered = sorted(ui_hits.items(), key=lambda item: (-len(item[1]), item[0]))
        primary = ordered[0][0] if ordered else ""
        secondary = [name for name, _evidence in ordered[1:]]
        evidence = [entry for _framework, entries in ordered for entry in entries]
        cms_primary = cms_ordered[0][0] if cms_ordered else ""
        ui_frameworks = [name for name, _evidence in ui_ordered]
        confidence = "low"
        if ordered and len(ordered[0][1]) >= 3:
            confidence = "high"
        elif ordered and len(ordered[0][1]) >= 1:
            confidence = "medium"
        if not primary and cms_primary:
            primary = cms_primary
            evidence = [entry for _framework, entries in cms_ordered for entry in entries]
            confidence = "high" if len(cms_ordered[0][1]) >= 3 else "medium"
        if primary:
            detected_count += 1
        if args.debug and primary:
            log_step(
                f"detection for {homepage_url}: framework={primary} cms={cms_primary or '-'} "
                f"ui={','.join(ui_frameworks) or '-'} confidence={confidence}"
            )

        detections.append(
            {
                "_id": entity["_id"],
                "Codice_IPA": entity["Codice_IPA"],
                "Denominazione_ente": entity["Denominazione_ente"],
                "Tipologia": entity["Tipologia"],
                "homepage_url": homepage_url,
                "homepage_status": homepage_record.get("status", ""),
                "framework_primario": primary,
                "framework_secondari": secondary,
                "cms_primario": cms_primary,
                "ui_frameworks": ui_frameworks,
                "confidence": confidence,
                "js_count": len([item for item in inventory_by_homepage.get(homepage_url, []) if item.get("status") == "ok"]),
                "css_count": len([item for item in css_by_homepage.get(homepage_url, []) if item.get("status") == "ok"]),
                "evidenze": evidence,
            }
        )
        if args.progress_every > 0 and index % args.progress_every == 0:
            elapsed = time.monotonic() - t_start
            detected_pct = detected_count * 100 // max(index, 1)
            log_progress(
                "detect-frameworks",
                index,
                len(entities),
                extra=f"detected={detected_count} ({detected_pct}%) {rate_str(elapsed, index, 'ent')}",
            )

    write_jsonl(args.output, detections)
    elapsed = time.monotonic() - t_start
    undetected = len(detections) - detected_count
    detected_pct = detected_count * 100 // max(len(detections), 1)
    log_step(
        f"Wrote {len(detections)} detection records to {args.output} | "
        f"detected={detected_count} ({detected_pct}%) undetected={undetected} "
        f"elapsed={elapsed_str(elapsed)}"
    )
    top_frameworks = Counter(
        str(d.get("framework_primario", "")) for d in detections if d.get("framework_primario")
    ).most_common(8)
    if top_frameworks:
        log_step("Top frameworks detected:")
        for name, count in top_frameworks:
            pct = count * 100 // max(len(detections), 1)
            log_step(f"  {name}: {count} ({pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
