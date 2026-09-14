from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _dump_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _review_priority(stats: dict) -> str:
    statement = stats.get("statement_health") or "unknown"
    coverage = stats.get("true_actionable_semantic_label_coverage")
    if coverage is None:
        coverage = stats.get("actionable_semantic_label_coverage")
    if coverage is None:
        coverage = stats.get("semantic_label_coverage")
    unresolved = stats.get("unresolved", 0) or 0
    unknown = stats.get("semantic_unknown_financial_labels")
    if unknown is None:
        unknown = stats.get("unknown_financial_labels", 0) or 0
    if statement.startswith("critical_"):
        return "P0"
    if statement.startswith("source_"):
        return "P1"
    if statement.startswith("schema_sector_gap"):
        return "P2"
    if unresolved > 0:
        return "P1"
    if isinstance(coverage, (int, float)) and coverage < 0.30:
        return "P1"
    if isinstance(coverage, (int, float)) and coverage < 0.45:
        return "P2"
    if unknown >= 80:
        return "P2"
    return "P3"


def build_coverage_report(results: list[tuple[Path, dict]], output_dir: str | Path, top_n: int = 100) -> dict:
    output_dir = Path(output_dir)
    rows = []
    global_labels = Counter()
    label_tickers = defaultdict(set)
    label_classes = defaultdict(Counter)
    class_counts = Counter()
    actionable_labels = Counter()
    actionable_tickers = defaultdict(set)
    actionable_classes = defaultdict(Counter)
    true_actionable_labels = Counter()
    true_actionable_tickers = defaultdict(set)
    true_actionable_classes = defaultdict(Counter)

    for path, result in results:
        stats = result["debug"]["stats"]
        coverage = result["debug"].get("semantic_coverage") or {}
        sector = result["debug"].get("sector_qa") or {}
        unknown_items = coverage.get("unknown_items") or coverage.get("unknown_examples") or []
        for item in unknown_items:
            norm = item.get("normalized_label") or item.get("label") or ""
            if not norm:
                continue
            cls = item.get("classification") or "unclassified"
            global_labels[norm] += 1
            label_tickers[norm].add(path.stem)
            label_classes[norm][cls] += 1
            class_counts[cls] += 1
            if cls not in {"noise", "review_generic_label"}:
                actionable_labels[norm] += 1
                actionable_tickers[norm].add(path.stem)
                actionable_classes[norm][cls] += 1
            if cls not in {"noise", "review_generic_label"}:
                true_actionable_labels[norm] += 1
                true_actionable_tickers[norm].add(path.stem)
                true_actionable_classes[norm][cls] += 1

        rows.append({
            "ticker": path.stem.split("_")[0],
            "source_name": path.name,
            "sector": sector.get("detected_sector"),
            "statement_health": stats.get("statement_health"),
            "scope_health": stats.get("scope_health"),
            "resolved": stats.get("resolved_before_dedup"),
            "unresolved": stats.get("unresolved"),
            "financial_label_candidates": stats.get("financial_label_candidates"),
            "matched_financial_labels": stats.get("matched_financial_labels"),
            "unknown_financial_labels": stats.get("unknown_financial_labels"),
            "actionable_unknown_financial_labels": stats.get("actionable_unknown_financial_labels"),
            "ambiguous_financial_labels": stats.get("ambiguous_financial_labels"),
            "semantic_label_coverage": stats.get("semantic_label_coverage"),
            "actionable_semantic_label_coverage": stats.get("actionable_semantic_label_coverage"),
            "true_actionable_semantic_label_coverage": stats.get("true_actionable_semantic_label_coverage"),
            "raw_unknown_financial_labels": stats.get("raw_unknown_financial_labels"),
            "noise_unknown_financial_labels": stats.get("noise_unknown_financial_labels"),
            "off_balance_unknown_financial_labels": stats.get("off_balance_unknown_financial_labels"),
            "sector_schema_unknown_financial_labels": stats.get("sector_schema_unknown_financial_labels"),
            "semantic_unknown_financial_labels": stats.get("semantic_unknown_financial_labels"),
            "generic_review_financial_labels": stats.get("generic_review_financial_labels"),
            "structural_gap_financial_labels": stats.get("structural_gap_financial_labels"),
            "true_actionable_unknown_financial_labels": stats.get("true_actionable_unknown_financial_labels"),
            "schema_sector_gap": stats.get("schema_sector_gap"),
            "explicit_total_missed": stats.get("explicit_total_missed"),
            "review_priority": _review_priority(stats),
            "unknown_top_labels": coverage.get("unknown_top_labels") or [],
            "unknown_classification_counts": coverage.get("unknown_classification_counts") or {},
        })

    rows.sort(key=lambda r: (
        {"P0":0,"P1":1,"P2":2,"P3":3}.get(r["review_priority"], 9),
        r["true_actionable_semantic_label_coverage"] if isinstance(r["true_actionable_semantic_label_coverage"], (int,float)) else 9,
        -(r["unknown_financial_labels"] or 0),
        r["ticker"],
    ))

    freq = []
    for label, count in global_labels.most_common(top_n):
        classes = label_classes[label]
        freq.append({
            "normalized_label": label,
            "occurrences": count,
            "ticker_count": len(label_tickers[label]),
            "tickers": sorted(label_tickers[label]),
            "classification_counts": dict(classes),
            "dominant_classification": classes.most_common(1)[0][0] if classes else None,
        })

    actionable_freq = []
    for label, count in actionable_labels.most_common(top_n):
        classes = actionable_classes[label]
        actionable_freq.append({
            "normalized_label": label,
            "occurrences": count,
            "ticker_count": len(actionable_tickers[label]),
            "tickers": sorted(actionable_tickers[label]),
            "classification_counts": dict(classes),
            "dominant_classification": classes.most_common(1)[0][0] if classes else None,
        })

    true_actionable_freq = []
    for label, count in true_actionable_labels.most_common(top_n):
        classes = true_actionable_classes[label]
        true_actionable_freq.append({
            "normalized_label": label,
            "occurrences": count,
            "ticker_count": len(true_actionable_tickers[label]),
            "tickers": sorted(true_actionable_tickers[label]),
            "classification_counts": dict(classes),
            "dominant_classification": classes.most_common(1)[0][0] if classes else None,
        })

    report = {
        "summary": {
            "files": len(rows),
            "p0": sum(r["review_priority"] == "P0" for r in rows),
            "p1": sum(r["review_priority"] == "P1" for r in rows),
            "p2": sum(r["review_priority"] == "P2" for r in rows),
            "p3": sum(r["review_priority"] == "P3" for r in rows),
            "unknown_classification_counts": dict(class_counts),
        },
        "files": rows,
        "unknown_label_frequency": freq,
        "actionable_unknown_label_frequency": actionable_freq,
        "true_actionable_unknown_label_frequency": true_actionable_freq,
    }

    cov_dir = output_dir / "coverage"
    _dump_json(cov_dir / "coverage_summary.json", report)
    _dump_json(cov_dir / "unknown_label_frequency.json", freq)
    _dump_json(cov_dir / "actionable_unknown_label_frequency.json", actionable_freq)
    _dump_json(cov_dir / "true_actionable_unknown_label_frequency.json", true_actionable_freq)

    csv_path = cov_dir / "coverage_summary.csv"
    fields = [
        "ticker","source_name","sector","statement_health","scope_health",
        "resolved","unresolved","financial_label_candidates","matched_financial_labels",
        "unknown_financial_labels","actionable_unknown_financial_labels","true_actionable_unknown_financial_labels",
        "noise_unknown_financial_labels","off_balance_unknown_financial_labels","sector_schema_unknown_financial_labels",
        "semantic_unknown_financial_labels","generic_review_financial_labels","structural_gap_financial_labels",
        "ambiguous_financial_labels","semantic_label_coverage","actionable_semantic_label_coverage","true_actionable_semantic_label_coverage",
        "schema_sector_gap","explicit_total_missed","review_priority",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})

    return report
