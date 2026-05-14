from __future__ import annotations

import argparse
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from common import (
    DATA_DIR,
    RESULTS_DIR,
    elapsed_str,
    ensure_directories,
    iter_jsonl,
    log_progress,
    log_step,
    rate_str,
    read_csv_rows,
    write_jsonl,
)


@dataclass(frozen=True)
class Fingerprint:
    technology: str
    family: str
    source_kind: str
    markers: tuple[str, ...]
    weight: float
    strong: bool = False
    cap: int = 1


@dataclass(frozen=True)
class EvidenceMatch:
    technology: str
    family: str
    source_kind: str
    source_label: str
    marker: str
    weight: float
    strong: bool
    cap: int

    def as_text(self) -> str:
        if self.source_label:
            return f"{self.source_kind}:{self.source_label}:{self.marker}"
        return f"{self.source_kind}:{self.marker}"


FINGERPRINTS = [
    Fingerprint("WordPress", "cms", "html", ("wp-content", "wp-includes", "wp-json"), 5.0, strong=True, cap=2),
    Fingerprint("WordPress", "cms", "meta", ("wordpress",), 7.0, strong=True),
    Fingerprint("WordPress", "cms", "url", ("wp-content", "wp-includes", "wp-json"), 3.0, cap=2),
    Fingerprint("WordPress", "cms", "url", ("elementor", "woocommerce"), 2.0, cap=1),
    Fingerprint("WordPress", "cms", "css-url", ("wp-content", "wp-includes"), 2.5, cap=2),
    Fingerprint("WordPress", "cms", "content", ("wp-api-fetch", "wp.i18n", "woocommerce"), 2.0, cap=1),
    Fingerprint("Drupal", "cms", "html", ("drupalsettings",), 7.0, strong=True),
    Fingerprint("Drupal", "cms", "meta", ("drupal",), 6.0, strong=True),
    Fingerprint("Drupal", "cms", "url", ("sites/default/files", "drupal"), 3.5, cap=2),
    Fingerprint("Drupal", "cms", "content", ("drupal", "drupalsettings"), 3.5, cap=1),
    Fingerprint("Joomla", "cms", "html", ("joomla",), 5.0, strong=True),
    Fingerprint("Joomla", "cms", "meta", ("joomla",), 6.0, strong=True),
    Fingerprint("Joomla", "cms", "url", ("joomla",), 3.0, cap=2),
    Fingerprint("Liferay", "cms", "html", ("liferay.themedisplay", "liferay.loader", "__liferay__", "themedisplay"), 7.0, strong=True, cap=2),
    Fingerprint("Liferay", "cms", "url", ("/o/", "__liferay__"), 4.0, cap=2),
    Fingerprint("Liferay", "cms", "content", ("liferay.loader", "liferay.themedisplay", "liferay.portlet", "@liferay/"), 4.0, strong=True, cap=2),
    Fingerprint("Django", "framework", "html", ("csrfmiddlewaretoken", "__admin_media_prefix__"), 6.0, strong=True, cap=2),
    Fingerprint("Django", "framework", "url", ("/static/admin/", "/static/admin/js/", "/static/admin/css/"), 5.0, strong=True, cap=2),
    Fingerprint("Django", "framework", "content", ("csrfmiddlewaretoken", "django.jquery", "__admin_media_prefix__"), 4.0, cap=2),
    Fingerprint("Django", "framework", "headers", ("x-powered-by: django", "server: gunicorn", "server: uwsgi"), 3.0, cap=1),
    Fingerprint("Django", "framework", "cookie", ("csrftoken", "django_language"), 2.5, cap=2),
    Fingerprint("Laravel", "framework", "url", ("/livewire/livewire.js", "/vendor/livewire/", "/_ignition/"), 5.0, strong=True, cap=2),
    Fingerprint("Laravel", "framework", "content", ("livewire",), 3.5, cap=1),
    Fingerprint("Laravel", "framework", "cookie", ("laravel_session",), 4.0, strong=True, cap=1),
    Fingerprint("Laravel", "framework", "cookie", ("xsrf-token",), 2.0, cap=1),
    Fingerprint("ASP.NET", "framework", "html", ("__viewstate", "__eventvalidation"), 6.0, strong=True, cap=2),
    Fingerprint("ASP.NET", "framework", "url", ("webresource.axd", "scriptresource.axd", "/aspnet_client/"), 5.0, strong=True, cap=2),
    Fingerprint("ASP.NET", "framework", "content", ("__dopostback", "sys.webforms.pagerequestmanager"), 4.0, cap=2),
    Fingerprint("ASP.NET", "framework", "headers", ("x-aspnet-version", "x-aspnetmvc-version", "x-powered-by: asp.net"), 6.0, strong=True, cap=2),
    Fingerprint("ASP.NET", "framework", "cookie", ("asp.net_sessionid", "__requestverificationtoken"), 4.0, cap=2),
    Fingerprint("Next.js", "framework", "html", ('id="__next"', "__next_data__"), 7.0, strong=True, cap=2),
    Fingerprint("Next.js", "framework", "inline-script", ("__next_data__", "self.__next_f"), 7.0, strong=True, cap=2),
    Fingerprint("Next.js", "framework", "url", ("/_next/", "__next"), 5.0, strong=True, cap=2),
    Fingerprint("Next.js", "framework", "content", ("__next_data__", "self.__next_f"), 6.0, strong=True, cap=2),
    Fingerprint("Nuxt", "framework", "html", ("__nuxt__", 'id="__nuxt"'), 7.0, strong=True, cap=2),
    Fingerprint("Nuxt", "framework", "inline-script", ("window.__nuxt__", "__nuxt__"), 7.0, strong=True, cap=2),
    Fingerprint("Nuxt", "framework", "url", ("/_nuxt/",), 5.0, strong=True, cap=2),
    Fingerprint("Nuxt", "framework", "content", ("window.__nuxt__", "__nuxt__"), 6.0, strong=True, cap=2),
    Fingerprint("Blazor", "framework", "html", ("/_framework/blazor", "blazor-error-ui"), 7.0, strong=True, cap=2),
    Fingerprint("Blazor", "framework", "url", ("/_framework/", "blazor"), 5.0, strong=True, cap=2),
    Fingerprint("Angular", "framework", "html", ("ng-version",), 7.0, strong=True),
    Fingerprint("Angular", "framework", "inline-script", ("ng-version",), 5.0, strong=True),
    Fingerprint("Angular", "framework", "content", ("@angular", "zone.js"), 4.0, cap=2),
    Fingerprint("Vue", "framework", "html", ("data-v-",), 4.0, cap=2),
    Fingerprint("Vue", "framework", "inline-script", ("__vue__", "createapp("), 4.5, cap=2),
    Fingerprint("Vue", "framework", "content", ("__vue__", "createapp(", "vue.runtime"), 3.5, cap=2),
    Fingerprint("React", "framework", "html", ('id="__next"',), 1.0, cap=1),
    Fingerprint("React", "framework", "content", ("react.production", "react-dom", "__react"), 3.0, cap=2),
    Fingerprint("React", "framework", "content", ("react",), 2.0, cap=1),
    Fingerprint("React", "framework", "content", ("createelement",), 0.75, cap=1),
    Fingerprint("jQuery", "library", "content", ("$.fn.jquery",), 2.0, cap=1),
    Fingerprint("jQuery", "library", "content", ("jquery",), 1.0, cap=1),
    Fingerprint("Bootstrap Italia", "ui", "html", ("bootstrap-italia", "bootstrap_italia", "--bootstrap-italia-version"), 5.0, strong=True, cap=2),
    Fingerprint("Bootstrap Italia", "ui", "css-url", ("bootstrap-italia", "bootstrap_italia"), 4.0, strong=True, cap=2),
    Fingerprint("Bootstrap Italia", "ui", "content", ("bootstrap-italia", "--bootstrap-italia-version", "bootstrapitalia"), 4.0, strong=True, cap=2),
    Fingerprint("Bootstrap", "ui", "css-url", ("bootstrap",), 2.0, cap=2),
    Fingerprint("Bootstrap", "ui", "content", ("data-bs-toggle",), 2.0, cap=1),
    Fingerprint("Bootstrap", "ui", "content", ("bootstrap",), 1.0, cap=1),
    Fingerprint("Tailwind CSS", "ui", "css-url", ("tailwind",), 3.0, strong=True, cap=2),
    Fingerprint("Bulma", "ui", "css-url", ("bulma",), 3.0, strong=True, cap=2),
    Fingerprint("Foundation", "ui", "css-url", ("foundation",), 3.0, strong=True, cap=2),
    Fingerprint("UIkit", "ui", "css-url", ("uikit",), 3.0, strong=True, cap=2),
    Fingerprint("Materialize", "ui", "css-url", ("materialize",), 3.0, strong=True, cap=2),
    Fingerprint("Elementor", "ui", "css-url", ("elementor",), 3.5, strong=True, cap=2),
    Fingerprint("Alpine.js", "framework", "content", ("alpine", "x-data"), 2.5, cap=1),
    Fingerprint("Svelte", "framework", "content", ("sveltecomponent",), 3.0, cap=1),
    Fingerprint("Stimulus", "framework", "content", ("stimulus", "data-controller"), 2.5, cap=1),
]
FINGERPRINTS_BY_SOURCE: dict[str, list[Fingerprint]] = defaultdict(list)
for fingerprint in FINGERPRINTS:
    FINGERPRINTS_BY_SOURCE[fingerprint.source_kind].append(fingerprint)

GENERIC_FRAMEWORKS = {"React", "Vue", "jQuery"}
PRIMARY_APPLICATION_FAMILIES = {"framework", "library"}
NOISY_THIRD_PARTY_HOST_KEYWORDS = (
    "addtoany",
    "cookieyes",
    "googletagmanager",
    "google-analytics",
    "google.com",
    "gstatic",
    "doubleclick",
    "hs-scripts",
    "hubspot",
    "iubenda",
    "clarity.ms",
    "cookiebot",
    "onetrust",
    "hotjar",
    "facebook.net",
    "twitter.com",
    "youtube.com",
)
BACKEND_HINT_RULES = {
    "PHP": (
        ("header", "x-powered-by", "php"),
        ("cookie", "", "phpsessid"),
        ("cookie", "", "laravel_session"),
    ),
    "Python": (
        ("header", "server", "gunicorn"),
        ("header", "server", "uwsgi"),
        ("header", "x-powered-by", "python"),
    ),
    "Node.js": (
        ("header", "x-powered-by", "express"),
        ("header", "x-powered-by", "node"),
        ("header", "server", "node"),
    ),
    "Java": (
        ("header", "server", "tomcat"),
        ("header", "server", "jetty"),
        ("header", "server", "undertow"),
        ("cookie", "", "jsessionid"),
    ),
}


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


def normalize_marker(marker: str) -> str:
    return marker.lower()


def extract_meta_text(html_text: str) -> str:
    meta_tags = re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE)
    return "\n".join(meta_tags)


def extract_inline_script_text(html_text: str) -> str:
    scripts = re.findall(
        r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return "\n".join(scripts)


def extract_headers_text(headers: dict[str, object]) -> str:
    lines = []
    for key, value in headers.items():
        text_key = str(key or "").strip().lower()
        text_value = str(value or "").strip()
        if text_key and text_value:
            lines.append(f"{text_key}: {text_value}")
    return "\n".join(lines)


def extract_cookie_text(cookies: list[object]) -> str:
    return "\n".join(str(cookie or "").strip().lower() for cookie in cookies if str(cookie or "").strip())


def is_noisy_third_party_host(hostname: str) -> bool:
    lowered = (hostname or "").lower()
    return any(keyword in lowered for keyword in NOISY_THIRD_PARTY_HOST_KEYWORDS)


def record_matches(
    sink: set[EvidenceMatch],
    text: str,
    source_kind: str,
    source_label: str,
    allowed_technologies: set[str] | None = None,
) -> None:
    if not text:
        return
    lowered = text.lower()
    for fingerprint in FINGERPRINTS_BY_SOURCE.get(source_kind, []):
        if allowed_technologies is not None and fingerprint.technology not in allowed_technologies:
            continue
        for marker in fingerprint.markers:
            normalized = normalize_marker(marker)
            if normalized in lowered:
                sink.add(
                    EvidenceMatch(
                        technology=fingerprint.technology,
                        family=fingerprint.family,
                        source_kind=source_kind,
                        source_label=source_label,
                        marker=normalized,
                        weight=fingerprint.weight,
                        strong=fingerprint.strong,
                        cap=fingerprint.cap,
                    )
                )


def prefer_bootstrap_italia(ranked: list[dict[str, object]]) -> list[dict[str, object]]:
    if not any(str(item["technology"]) == "Bootstrap Italia" for item in ranked):
        return ranked
    return [item for item in ranked if str(item["technology"]) != "Bootstrap"]


def aggregate_matches(matches: set[EvidenceMatch]) -> list[dict[str, object]]:
    grouped: dict[str, dict[tuple[str, str], dict[str, object]]] = defaultdict(dict)
    technology_family: dict[str, str] = {}
    technology_evidence: dict[str, set[str]] = defaultdict(set)
    technology_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    technology_strong_markers: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for match in matches:
        technology_family[match.technology] = match.family
        technology_evidence[match.technology].add(match.as_text())
        technology_by_source[match.technology][match.source_kind] += 1
        key = (match.source_kind, match.marker)
        bucket = grouped[match.technology].setdefault(
            key,
            {
                "weight": match.weight,
                "cap": match.cap,
                "source_labels": set(),
                "strong": match.strong,
            },
        )
        bucket["source_labels"].add(match.source_label or "")
        if match.strong:
            technology_strong_markers[match.technology].add((match.source_kind, match.marker))

    ranked: list[dict[str, object]] = []
    for technology, buckets in grouped.items():
        score = 0.0
        unique_markers = set()
        for (source_kind, marker), bucket in buckets.items():
            unique_markers.add((source_kind, marker))
            hit_count = len(bucket["source_labels"])
            contribution = float(bucket["weight"]) * min(hit_count, int(bucket["cap"]))
            score += contribution
        ranked.append(
            {
                "technology": technology,
                "family": technology_family[technology],
                "score": round(score, 2),
                "strong_evidence_count": len(technology_strong_markers[technology]),
                "unique_marker_count": len(unique_markers),
                "evidence": sorted(technology_evidence[technology]),
                "evidence_by_source": dict(technology_by_source[technology]),
            }
        )

    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            -int(item["strong_evidence_count"]),
            -int(item["unique_marker_count"]),
            str(item["technology"]),
        )
    )
    return prefer_bootstrap_italia(ranked)


def select_primary_cms(ranked: list[dict[str, object]]) -> str:
    cms_ranked = [item for item in ranked if item["family"] == "cms"]
    if not cms_ranked:
        return ""
    best = cms_ranked[0]
    if float(best["score"]) >= 4.0 or int(best["strong_evidence_count"]) >= 1:
        return str(best["technology"])
    return ""


def select_primary_framework(ranked: list[dict[str, object]], cms_primary: str) -> str:
    technology_map = {str(item["technology"]): item for item in ranked}
    non_ui_ranked = [item for item in ranked if item["family"] != "ui"]
    non_cms_ranked = [
        item
        for item in non_ui_ranked
        if item["family"] != "cms" and item["family"] in PRIMARY_APPLICATION_FAMILIES
    ]

    app_primary = str(non_cms_ranked[0]["technology"]) if non_cms_ranked else ""
    if not cms_primary:
        if not app_primary:
            return ""
        app_score = float(technology_map[app_primary]["score"])
        app_strong = int(technology_map[app_primary]["strong_evidence_count"])
        if app_primary in GENERIC_FRAMEWORKS and app_score < 4.0 and app_strong == 0:
            return ""
        if app_score < 3.0 and app_strong == 0:
            return ""
        return app_primary

    cms_score = float(technology_map[cms_primary]["score"])
    if not app_primary:
        return cms_primary

    app_score = float(technology_map[app_primary]["score"])
    app_strong = int(technology_map[app_primary]["strong_evidence_count"])

    if app_primary in GENERIC_FRAMEWORKS and cms_score >= app_score:
        return cms_primary
    if cms_score >= app_score and app_strong < 2:
        return cms_primary
    if cms_score >= app_score + 4.0:
        return cms_primary
    if app_strong == 0 and cms_score > app_score:
        return cms_primary
    if app_score < 4.0 and cms_score >= app_score:
        return cms_primary
    return app_primary


def select_secondary_frameworks(ranked: list[dict[str, object]], primary: str) -> list[str]:
    secondary = []
    for item in ranked:
        technology = str(item["technology"])
        if technology == primary or item["family"] == "ui":
            continue
        if float(item["score"]) < 1.0:
            continue
        secondary.append(technology)
    return secondary


def select_ui_frameworks(ranked: list[dict[str, object]]) -> list[str]:
    ui_ranked = [item for item in ranked if item["family"] == "ui" and float(item["score"]) >= 2.0]
    return [str(item["technology"]) for item in ui_ranked]


def confidence_for_primary(primary: str, ranked: list[dict[str, object]]) -> str:
    if not primary:
        return "low"
    tech_map = {str(item["technology"]): item for item in ranked}
    current = tech_map[primary]
    score = float(current["score"])
    strong = int(current["strong_evidence_count"])
    unique_markers = int(current["unique_marker_count"])
    if strong >= 2 or score >= 10.0:
        return "high"
    if strong >= 1 or score >= 4.0 or unique_markers >= 2:
        return "medium"
    return "low"


def infer_backend_hints(homepage_record: dict[str, object]) -> list[str]:
    headers = {
        str(key or "").lower(): str(value or "").lower()
        for key, value in dict(homepage_record.get("response_headers", {}) or {}).items()
    }
    cookies = {str(cookie or "").lower() for cookie in homepage_record.get("set_cookie_names", []) or []}
    hints = set()
    for hint_name, rules in BACKEND_HINT_RULES.items():
        for rule_type, header_name, marker in rules:
            marker_text = marker.lower()
            if rule_type == "header":
                if marker_text in headers.get(header_name.lower(), ""):
                    hints.add(hint_name)
                    break
            elif rule_type == "cookie" and marker_text in cookies:
                hints.add(hint_name)
                break
    return sorted(hints)


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
        homepage_host = urlparse(homepage_url).netloc.lower()
        homepage_record = homepage_records.get(homepage_url, {})
        matches: set[EvidenceMatch] = set()

        saved_html = str(homepage_record.get("saved_html_path", "")) if homepage_record else ""
        html_path = Path(saved_html) if saved_html else None
        if html_path and html_path.exists():
            html_text = html_path.read_text(encoding="utf-8", errors="ignore")[:200_000]
            meta_text = extract_meta_text(html_text)
            inline_script_text = extract_inline_script_text(html_text)
            record_matches(matches, html_text, "html", html_path.name)
            record_matches(matches, meta_text, "meta", html_path.name)
            record_matches(matches, inline_script_text, "inline-script", html_path.name)
        response_headers = dict(homepage_record.get("response_headers", {}) or {})
        set_cookie_names = list(homepage_record.get("set_cookie_names", []) or [])
        record_matches(matches, extract_headers_text(response_headers), "headers", homepage_host)
        record_matches(matches, extract_cookie_text(set_cookie_names), "cookie", homepage_host)

        for item in inventory_by_homepage.get(homepage_url, []):
            script_url = str(item.get("script_url", ""))
            script_hostname = str(item.get("script_hostname", "")).lower()
            source_label = script_hostname or homepage_host
            if script_url and not is_noisy_third_party_host(script_hostname):
                record_matches(matches, script_url, "url", source_label)

            download = downloads_by_url.get(script_url)
            if download and download.get("status") == "ok" and not is_noisy_third_party_host(script_hostname):
                saved_path = Path(str(download["saved_path"]))
                if saved_path.exists():
                    content_source_label = f"{script_hostname or homepage_host}/{saved_path.name}"
                    record_matches(
                        matches,
                        saved_path.read_text(encoding="utf-8", errors="ignore")[:200_000],
                        "content",
                        content_source_label,
                    )

        for item in css_by_homepage.get(homepage_url, []):
            css_url = str(item.get("css_url", ""))
            css_hostname = urlparse(css_url).netloc.lower() or homepage_host
            if css_url and not is_noisy_third_party_host(css_hostname):
                record_matches(matches, css_url, "css-url", css_hostname)

        ranked = aggregate_matches(matches)
        cms_primary = select_primary_cms(ranked)
        primary = select_primary_framework(ranked, cms_primary)
        secondary = select_secondary_frameworks(ranked, primary)
        ui_frameworks = select_ui_frameworks(ranked)
        confidence = confidence_for_primary(primary, ranked)
        backend_hints = infer_backend_hints(homepage_record)
        evidence = []
        for item in ranked:
            evidence.extend(item["evidence"])
        technology_scores = [
            {
                "technology": item["technology"],
                "family": item["family"],
                "score": item["score"],
                "strong_evidence_count": item["strong_evidence_count"],
                "unique_marker_count": item["unique_marker_count"],
            }
            for item in ranked
        ]
        evidence_by_source = Counter()
        for item in ranked:
            evidence_by_source.update(item["evidence_by_source"])

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
                "backend_hints": backend_hints,
                "confidence": confidence,
                "js_count": len([item for item in inventory_by_homepage.get(homepage_url, []) if item.get("status") == "ok"]),
                "css_count": len([item for item in css_by_homepage.get(homepage_url, []) if item.get("status") == "ok"]),
                "evidenze": evidence,
                "technology_scores": technology_scores,
                "evidence_by_source": dict(evidence_by_source),
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
