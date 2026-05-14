from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from common import RESULTS_DIR, ensure_directories, iter_jsonl, log_step


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera una pagina web statica con i risultati")
    parser.add_argument("--input", type=Path, default=RESULTS_DIR / "framework_detection.jsonl")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "report.html")
    parser.add_argument("--title", default="Framework Census Report")
    return parser.parse_args()


def build_summary(records: list[dict[str, object]]) -> dict[str, object]:
    framework_counts = Counter(
        str(record.get("framework_primario", "")).strip()
        for record in records
        if str(record.get("framework_primario", "")).strip()
    )
    cms_counts = Counter(
        str(record.get("cms_primario", "")).strip()
        for record in records
        if str(record.get("cms_primario", "")).strip()
    )
    ui_counts = Counter(
        framework
        for record in records
        for framework in record.get("ui_frameworks", [])
        if framework
    )
    confidence_counts = Counter(str(record.get("confidence", "")).strip() for record in records)
    return {
        "entities_total": len(records),
        "framework_counts": framework_counts.most_common(12),
        "cms_counts": cms_counts.most_common(12),
        "ui_counts": ui_counts.most_common(12),
        "confidence_counts": confidence_counts,
    }


def sanitize_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    def sanitize_evidence_entry(value: object) -> str:
        text = str(value or "")
        parts = text.split(":")
        if len(parts) >= 3:
            return f"{parts[0]}:{parts[-1]}"
        return text

    sanitized = []
    for record in records:
        sanitized.append(
            {
                "_id": record.get("_id", ""),
                "Codice_IPA": record.get("Codice_IPA", ""),
                "Tipologia": record.get("Tipologia", ""),
                "framework_primario": record.get("framework_primario", ""),
                "framework_secondari": list(record.get("framework_secondari", [])),
                "cms_primario": record.get("cms_primario", ""),
                "ui_frameworks": list(record.get("ui_frameworks", [])),
                "confidence": record.get("confidence", ""),
                "js_count": record.get("js_count", 0),
                "css_count": record.get("css_count", 0),
                "homepage_status": record.get("homepage_status", ""),
                "evidenze": [sanitize_evidence_entry(value) for value in record.get("evidenze", [])],
            }
        )
    return sanitized


def render_html(title: str, records: list[dict[str, object]], summary: dict[str, object]) -> str:
    payload = {"title": title, "records": records, "summary": summary}
    payload_json = json.dumps(payload, ensure_ascii=True)
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f5efe4;
      --paper: #fffdf8;
      --ink: #1f2933;
      --muted: #5b6670;
      --accent: #0f766e;
      --accent-2: #b45309;
      --line: #e6dcc8;
      --chip: #efe4cf;
      --chip-2: #d9efe9;
      --shadow: 0 20px 45px rgba(31, 41, 51, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15,118,110,.18), transparent 28%),
        radial-gradient(circle at top right, rgba(180,83,9,.14), transparent 22%),
        linear-gradient(180deg, #f7f1e7 0%, var(--bg) 100%);
    }}
    .wrap {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(15,118,110,.95), rgba(19,78,74,.95));
      color: white;
      border-radius: 28px;
      padding: 28px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 1;
      letter-spacing: -.03em;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: rgba(255,255,255,.88);
      max-width: 780px;
      font-size: 1rem;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 20px 0 28px;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .metric {{
      font-size: 2rem;
      font-weight: 700;
      margin-top: 6px;
    }}
    .label {{
      color: var(--muted);
      font-size: .92rem;
      text-transform: uppercase;
      letter-spacing: .08em;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 18px;
      align-items: start;
    }}
    .panel-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }}
    .panel-title h2 {{
      margin: 0;
      font-size: 1.1rem;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .filters input, .filters select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: white;
      color: var(--ink);
      font: inherit;
    }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid #f0e8d6;
      vertical-align: top;
      text-align: left;
      font-size: .94rem;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #faf4e8;
      z-index: 1;
    }}
    tr:hover td {{
      background: #fffcf6;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      background: var(--chip);
      color: #6b4f1d;
      font-size: .82rem;
      white-space: nowrap;
    }}
    .chip.alt {{
      background: var(--chip-2);
      color: #0f5f58;
    }}
    .confidence-high {{ color: #166534; font-weight: 700; }}
    .confidence-medium {{ color: #9a6700; font-weight: 700; }}
    .confidence-low {{ color: #6b7280; font-weight: 700; }}
    .bars {{
      display: grid;
      gap: 12px;
    }}
    .bar-row {{
      display: grid;
      gap: 8px;
    }}
    .bar-label {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: .92rem;
    }}
    .bar-track {{
      height: 10px;
      border-radius: 999px;
      background: #ede3cf;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      border-radius: 999px;
    }}
    .small {{
      font-size: .85rem;
      color: var(--muted);
    }}
    details {{
      margin-top: 6px;
    }}
    details summary {{
      cursor: pointer;
      color: var(--accent);
      font-weight: 600;
    }}
    pre {{
      margin: 8px 0 0;
      padding: 12px;
      border-radius: 14px;
      background: #fbf6eb;
      border: 1px solid var(--line);
      white-space: pre-wrap;
      word-break: break-word;
      font-size: .8rem;
    }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 20px 14px 32px; }}
      .hero {{ border-radius: 22px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{title}</h1>
      <p>Esplorazione interattiva dei risultati della pipeline: framework primario, CMS, librerie UI, confidenza e numero di asset rilevati per tipologia.</p>
    </section>

    <section class="stats" id="stats"></section>

    <section class="grid">
      <div class="card">
        <div class="panel-title">
          <h2>Record</h2>
          <div class="small" id="visible-count"></div>
        </div>
        <div class="filters">
          <input id="search" type="search" placeholder="Cerca framework, CMS, UI o tipologia...">
          <select id="framework-filter"><option value="">Tutti i framework</option></select>
          <select id="cms-filter"><option value="">Tutti i CMS</option></select>
          <select id="confidence-filter">
            <option value="">Tutte le confidenze</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
          <select id="tipologia-filter"><option value="">Tutte le tipologie</option></select>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Tipologia</th>
                <th>Framework</th>
                <th>CMS</th>
                <th>UI</th>
                <th>Confidenza</th>
                <th>Asset</th>
                <th>Evidenze</th>
              </tr>
            </thead>
            <tbody id="results-body"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="panel-title">
          <h2>Distribuzione</h2>
          <div class="small">Aggiornata con i filtri correnti</div>
        </div>
        <div class="bars" id="distribution"></div>
      </div>
    </section>
  </div>

  <script>
    const payload = {payload_json};
    const records = payload.records;

    const els = {{
      stats: document.getElementById('stats'),
      body: document.getElementById('results-body'),
      distribution: document.getElementById('distribution'),
      visibleCount: document.getElementById('visible-count'),
      search: document.getElementById('search'),
      framework: document.getElementById('framework-filter'),
      cms: document.getElementById('cms-filter'),
      confidence: document.getElementById('confidence-filter'),
      tipologia: document.getElementById('tipologia-filter'),
    }};

    function uniqueValues(key, transform = (v) => v) {{
      return [...new Set(records.map((r) => transform(r[key])).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }}

    function fillSelect(select, values) {{
      values.forEach((value) => {{
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
    }}

    fillSelect(els.framework, uniqueValues('framework_primario'));
    fillSelect(els.cms, uniqueValues('cms_primario'));
    fillSelect(els.tipologia, uniqueValues('Tipologia'));

    function renderStats(items) {{
      const total = items.length;
      const detected = items.filter((r) => r.framework_primario).length;
      const high = items.filter((r) => r.confidence === 'high').length;
      const jsTotal = items.reduce((acc, r) => acc + Number(r.js_count || 0), 0);
      const cssTotal = items.reduce((acc, r) => acc + Number(r.css_count || 0), 0);
      const cards = [
        ['Record visibili', total],
        ['Con framework', detected],
        ['Confidenza alta', high],
        ['JS rilevati', jsTotal],
        ['CSS rilevati', cssTotal],
      ];
      els.stats.innerHTML = cards.map(([label, value]) => `
        <article class="card">
          <div class="label">${{label}}</div>
          <div class="metric">${{Number(value).toLocaleString('it-IT')}}</div>
        </article>
      `).join('');
    }}

    function topCounts(items) {{
      const counts = new Map();
      items.forEach((item) => {{
        const key = item.framework_primario || item.cms_primario || 'Non identificato';
        counts.set(key, (counts.get(key) || 0) + 1);
      }});
      return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
    }}

    function renderDistribution(items) {{
      const rows = topCounts(items);
      const max = rows.length ? rows[0][1] : 1;
      els.distribution.innerHTML = rows.map(([label, count]) => `
        <div class="bar-row">
          <div class="bar-label"><span>${{label}}</span><strong>${{count}}</strong></div>
          <div class="bar-track"><div class="bar-fill" style="width:${{(count / max) * 100}}%"></div></div>
        </div>
      `).join('') || '<div class="small">Nessun dato per i filtri correnti.</div>';
    }}

    function confidenceClass(value) {{
      return `confidence-${{(value || 'low').toLowerCase()}}`;
    }}

    function chipList(values, alt = false) {{
      if (!values || !values.length) return '';
      return `<div class="chips">${{values.map((value) => `<span class="chip ${{alt ? 'alt' : ''}}">${{value}}</span>`).join('')}}</div>`;
    }}

    function evidencePreview(evidenze) {{
      if (!evidenze || !evidenze.length) return '<span class="small">Nessuna</span>';
      const preview = evidenze.slice(0, 5).join('\\n');
      return `
        <details>
          <summary>${{evidenze.length}} evidenze</summary>
          <pre>${{preview}}${{evidenze.length > 5 ? '\\n…' : ''}}</pre>
        </details>
      `;
    }}

    function renderRows(items) {{
      els.body.innerHTML = items.map((record) => `
        <tr>
          <td>
            <span class="small">${{record.Tipologia || ''}}</span>
          </td>
          <td>
            <strong>${{record.framework_primario || 'Non identificato'}}</strong>
            ${{chipList(record.framework_secondari || [], true)}}
          </td>
          <td>${{record.cms_primario || ''}}</td>
          <td>${{chipList(record.ui_frameworks || [])}}</td>
          <td><span class="${{confidenceClass(record.confidence)}}">${{record.confidence || 'low'}}</span></td>
          <td>
            <div>JS: <strong>${{record.js_count || 0}}</strong></div>
            <div>CSS: <strong>${{record.css_count || 0}}</strong></div>
          </td>
          <td>${{evidencePreview(record.evidenze || [])}}</td>
        </tr>
      `).join('');
      els.visibleCount.textContent = `${{items.length.toLocaleString('it-IT')}} record visibili`;
    }}

    function filterRecords() {{
      const query = els.search.value.trim().toLowerCase();
      const framework = els.framework.value;
      const cms = els.cms.value;
      const confidence = els.confidence.value;
      const tipologia = els.tipologia.value;

      const filtered = records.filter((record) => {{
        const haystack = [
          record.framework_primario,
          ...(record.framework_secondari || []),
          record.cms_primario,
          ...(record.ui_frameworks || []),
          record.Tipologia,
        ].join(' ').toLowerCase();
        if (query && !haystack.includes(query)) return false;
        if (framework && record.framework_primario !== framework) return false;
        if (cms && record.cms_primario !== cms) return false;
        if (confidence && record.confidence !== confidence) return false;
        if (tipologia && record.Tipologia !== tipologia) return false;
        return true;
      }});

      renderStats(filtered);
      renderRows(filtered);
      renderDistribution(filtered);
    }}

    [els.search, els.framework, els.cms, els.confidence, els.tipologia].forEach((el) => {{
      el.addEventListener('input', filterRecords);
      el.addEventListener('change', filterRecords);
    }});

    filterRecords();
  </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    ensure_directories()
    records = list(iter_jsonl(args.input))
    log_step(f"Building web report from {len(records)} records in {args.input}")
    summary = build_summary(records)
    html = render_html(args.title, sanitize_records(records), summary)
    args.output.write_text(html, encoding="utf-8")
    size_kb = len(html.encode("utf-8")) / 1024
    detected = sum(1 for r in records if r.get("framework_primario") or r.get("cms_primario"))
    detected_pct = detected * 100 // max(len(records), 1)
    log_step(
        f"Wrote web report to {args.output} ({size_kb:.0f}KB) | "
        f"entities={len(records)} detected={detected} ({detected_pct}%)"
    )
    log_step("Top frameworks in report:")
    for name, count in summary["framework_counts"][:5]:
        pct = count * 100 // max(len(records), 1)
        log_step(f"  {name}: {count} ({pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
