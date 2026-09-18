"""Tạo trình kiểm tra HTML nhỏ, không phụ thuộc thư viện, cho output JSON production."""

from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path
from typing import Any


def _value_by_period(values: list[dict[str, Any]]) -> tuple[Any, Any]:
    current = previous = None
    for value in values:
        role = (value.get("period") or {}).get("role")
        if role == "current":
            current = value.get("normalized")
        elif role == "previous":
            previous = value.get("normalized")
    return current, previous


def collect(output_dir: Path) -> dict[str, Any]:
    reports = []
    statement_rows = []
    note_rows = []
    for path in sorted((output_dir / "reports").glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        source = report["report"]["source"]
        source_name = source["name"]
        statements = report.get("statements") or {}
        for statement_name, statement in statements.items():
            for group in ("items", "observations"):
                for record in statement.get(group) or []:
                    value = record.get("value") or {}
                    evidence = (record.get("provenance") or {}).get("evidence") or []
                    first_evidence = evidence[0] if evidence else {}
                    statement_rows.append(
                        {
                            "report": source_name,
                            "statement": statement_name,
                            "type": group[:-1],
                            "label": record.get("label"),
                            "id": record.get("id"),
                            "current": value.get("current"),
                            "previous": value.get("previous"),
                            "unit": value.get("unit"),
                            "mapping": (record.get("provenance") or {}).get("mapping"),
                            "source_line": first_evidence.get("source_line"),
                            "raw_text": value.get("raw_text") or first_evidence.get("raw_text"),
                            "attributes": record.get("attributes"),
                            "provenance": record.get("provenance"),
                        }
                    )
        notes = report.get("notes") or {}
        for row in notes.get("rows") or []:
            current, previous = _value_by_period(row.get("values") or [])
            source_meta = row.get("source") or {}
            note = row.get("note") or {}
            label = row.get("label") or {}
            note_rows.append(
                {
                    "report": source_name,
                    "note": note.get("id") or note.get("title"),
                    "label": label.get("raw") or label.get("normalized"),
                    "id": row.get("id"),
                    "current": current,
                    "previous": previous,
                    "unit": ((row.get("context") or {}).get("unit") or {}).get("canonical"),
                    "source_line": source_meta.get("line"),
                    "raw_cells": source_meta.get("raw_cells"),
                    "links": row.get("links"),
                }
            )
        reports.append(
            {
                "name": source_name,
                "status": (report.get("quality") or {}).get("status"),
                "statement_count": sum(
                    len((statement.get("items") or [])) + len((statement.get("observations") or []))
                    for statement in statements.values()
                ),
                "note_count": len(notes.get("rows") or []),
            }
        )
    return {"reports": reports, "statements": statement_rows, "notes": note_rows}


HTML = r'''<!doctype html>
<meta charset="utf-8">
<title>Output inspector</title>
<style>
  :root {
    color-scheme: light;
    font: 14px system-ui, sans-serif;
    --background: #eef8ff;
    --surface: #ffffff;
    --foreground: #173f5f;
    --muted: #5f7d94;
    --border: #b9d9ee;
    --header: #d9efff;
    --hover: #c8e9ff;
    --accent: #0879b6;
  }
  body { margin: 24px; background: var(--background); color: var(--foreground); }
  h1 { margin: 0 0 6px; font-size: 22px; color: var(--accent); }
  .muted { color: var(--muted); }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 10px; }
  input, select { padding: 7px; min-width: 150px; background: var(--surface); color: var(--foreground); border: 1px solid var(--border); border-radius: 5px; }
  input { flex: 1 1 280px; }
  .stats { margin: 10px 0; }
  .table-wrap { overflow: auto; max-height: 68vh; border: 1px solid var(--border); background: var(--surface); }
  table { border-collapse: collapse; width: 100%; }
  th, td { padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
  th { position: sticky; top: 0; background: var(--header); color: var(--foreground); }
  tr[data-index] { cursor: pointer; }
  tr[data-index]:hover { background: var(--hover); color: var(--foreground); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  td.raw { max-width: 440px; white-space: pre-wrap; }
  pre { white-space: pre-wrap; max-height: 28vh; overflow: auto; padding: 12px; border: 1px solid var(--border); background: var(--surface); }
</style>
<h1>Output inspector</h1>
<div class="muted">Click a row to inspect its complete compact record.</div>
<div class="controls">
  <select id="dataset" aria-label="Dataset"><option value="statements">B01/B02/B03</option><option value="notes">Notes</option></select>
  <select id="report" aria-label="Report"><option value="">All reports</option></select>
  <input id="query" placeholder="Search report, label, id, raw text..." aria-label="Search">
  <label><input id="nonempty" type="checkbox"> only rows with values</label>
</div>
<div id="stats" class="stats" aria-live="polite"></div>
<div class="table-wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<h2>Selected row</h2><pre id="detail">Select a row.</pre>
<script>
const DATA = __DATA__;
const state = { dataset: 'statements', report: '', query: '', nonempty: false };
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const fmt = value => value == null ? '—' : typeof value === 'number' ? value.toLocaleString('vi-VN') : String(value);
function rows() {
  const source = DATA[state.dataset];
  const query = state.query.toLocaleLowerCase('vi');
  return source.filter(row => {
    const haystack = JSON.stringify(row).toLocaleLowerCase('vi');
    const hasValue = row.current != null || row.previous != null;
    return (!state.report || row.report === state.report) && (!query || haystack.includes(query)) && (!state.nonempty || hasValue);
  });
}
function renderReports() {
  const current = state.report;
  $('report').innerHTML = '<option value="">All reports</option>' + DATA.reports.map(r => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join('');
  $('report').value = current;
}
function render() {
  const result = rows();
  const visible = result.slice(0, 1500);
  const isNotes = state.dataset === 'notes';
  $('stats').textContent = `${result.length.toLocaleString('vi-VN')} rows${result.length > visible.length ? ` (showing first ${visible.length.toLocaleString('vi-VN')})` : ''} · ${DATA.reports.length} reports · statements ${DATA.statements.length.toLocaleString('vi-VN')} · notes ${DATA.notes.length.toLocaleString('vi-VN')}`;
  $('head').innerHTML = isNotes ? '<tr><th>Report</th><th>Note</th><th>Label</th><th>Current</th><th>Previous</th><th>Unit</th><th>Line</th></tr>' : '<tr><th>Report</th><th>Statement</th><th>Type</th><th>Label</th><th>Current</th><th>Previous</th><th>Mapping</th><th>Line</th><th>Raw text</th></tr>';
  $('body').innerHTML = visible.map((row, index) => isNotes
    ? `<tr data-index="${index}"><td>${esc(row.report)}</td><td>${esc(row.note)}</td><td>${esc(row.label)}</td><td class="num">${esc(fmt(row.current))}</td><td class="num">${esc(fmt(row.previous))}</td><td>${esc(row.unit)}</td><td>${esc(row.source_line)}</td></tr>`
    : `<tr data-index="${index}"><td>${esc(row.report)}</td><td>${esc(row.statement)}</td><td>${esc(row.type)}</td><td>${esc(row.label)}</td><td class="num">${esc(fmt(row.current))}</td><td class="num">${esc(fmt(row.previous))}</td><td>${esc((row.mapping || {}).status)}</td><td>${esc(row.source_line)}</td><td class="raw">${esc(row.raw_text)}</td></tr>`
  ).join('');
  [...$('body').querySelectorAll('tr[data-index]')].forEach((tr, index) => tr.onclick = () => $('detail').textContent = JSON.stringify(visible[index], null, 2));
}
DATA.reports.sort((a, b) => a.name.localeCompare(b.name));
renderReports(); render();
$('dataset').onchange = event => { state.dataset = event.target.value; render(); };
$('report').onchange = event => { state.report = event.target.value; render(); };
$('query').oninput = event => { state.query = event.target.value; render(); };
$('nonempty').onchange = event => { state.nonempty = event.target.checked; render(); };
</script>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/current"))
    parser.add_argument("--html", type=Path, default=Path("output/inspection/output_viewer.html"))
    parser.add_argument("--open", action="store_true", help="open the generated viewer in the default browser")
    args = parser.parse_args()
    payload = json.dumps(collect(args.output_dir), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    print(f"Viewer: {args.html.resolve()}")
    if args.open:
        webbrowser.open(args.html.resolve().as_uri())


if __name__ == "__main__":
    main()
