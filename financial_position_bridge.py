from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from source_observation_layer import augment_financial_position
from source_statement_recovery import extract_financial_position_source_rows, augment_canonical_with_recovered_rows
from source_reconciliation import reconcile_source_observations


GENERIC_CANONICAL_SUFFIX = ".canonical.json"
EXCLUDE_CANONICAL_MARKERS = (".income.canonical.json", ".cashflow.canonical.json", ".financial_position.canonical.json")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def stem_base(path: Path) -> str:
    name = path.stem
    return re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)


def canonical_base_name(path: Path) -> str:
    name = path.name
    if name.endswith(GENERIC_CANONICAL_SUFFIX):
        name = name[: -len(GENERIC_CANONICAL_SUFFIX)]
    name = re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)
    return name


def is_financial_position_canonical(path: Path) -> bool:
    low = path.name.lower()
    if not low.endswith(GENERIC_CANONICAL_SUFFIX):
        return False
    if any(low.endswith(x) for x in EXCLUDE_CANONICAL_MARKERS):
        return False
    obj = read_json(path, {})
    return isinstance(obj, dict) and obj.get("statement_type") == "FINANCIAL_POSITION" and obj.get("schema_id") == "UNIVERSAL_FINANCIAL_POSITION_V1"


@dataclass
class FinancialPositionIndex:
    by_base: dict[str, Path]
    scanned_files: int = 0

    @classmethod
    def build(cls, roots: Iterable[Path]) -> "FinancialPositionIndex":
        by_base: dict[str, Path] = {}
        scanned = 0
        seen_roots = set()
        for root in roots:
            if not root:
                continue
            try:
                rr = root.resolve()
            except Exception:
                rr = root
            if rr in seen_roots or not root.exists():
                continue
            seen_roots.add(rr)
            candidates = [root] if root.is_file() else root.rglob("*.canonical.json")
            for p in candidates:
                if not p.is_file():
                    continue
                scanned += 1
                if not is_financial_position_canonical(p):
                    continue
                base = canonical_base_name(p)
                current = by_base.get(base)
                # Prefer exact unsuffixed file, otherwise shorter path/name.
                if current is None:
                    by_base[base] = p
                else:
                    cur_exact = current.name == f"{base}.canonical.json"
                    new_exact = p.name == f"{base}.canonical.json"
                    if new_exact and not cur_exact:
                        by_base[base] = p
                    elif new_exact == cur_exact and len(str(p)) < len(str(current)):
                        by_base[base] = p
        return cls(by_base=by_base, scanned_files=scanned)

    def find(self, base: str) -> Optional[Path]:
        return self.by_base.get(base)


def _norm_number(v: Any):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s or s in {"-", "—", "–"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = re.sub(r"[^0-9,.-]", "", s)
    if not s:
        return None
    # Financial reports here predominantly use dots as thousands separators and comma as decimal.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "," in s:
        # decimal comma only when final group is short; otherwise thousands
        head, tail = s.rsplit(",", 1)
        if len(tail) <= 2:
            s = head.replace(",", "") + "." + tail
        else:
            s = s.replace(",", "")
    try:
        x = float(s) if "." in s else int(s)
        return -x if neg and x > 0 else x
    except Exception:
        return None


def summarize_canonical(canonical: dict, source_path: Optional[Path] = None, legacy_metrics: Optional[dict] = None) -> dict:
    nodes = canonical.get("nodes") or []
    valued = []
    current = []
    previous = []
    for n in nodes:
        val = n.get("value") or {}
        c, p = val.get("current"), val.get("previous")
        if c is not None or p is not None:
            valued.append(n)
        if c is not None:
            current.append(n)
        if p is not None:
            previous.append(n)
    valued_n = len(valued)
    metrics = {
        "status": "ok" if valued_n else "no_financial_position_values",
        "value_nodes": valued_n,
        "current_value_nodes": len(current),
        "previous_value_nodes": len(previous),
        "mapping": {
            "canonical_value_nodes": valued_n,
            "current_value_nodes": len(current),
            "previous_value_nodes": len(previous),
            "current_coverage": round(len(current) / valued_n, 6) if valued_n else 0.0,
            "previous_coverage": round(len(previous) / valued_n, 6) if valued_n else 0.0,
        },
        "parser": {
            "statement_profile": "financial_position",
            "schema_id": canonical.get("schema_id"),
            "schema_version": canonical.get("schema_version"),
            "integration_mode": "reuse_completed_canonical",
            "source_canonical": source_path.name if source_path else None,
        },
    }
    # Preserve richer previously-computed B02 metrics when they exist.
    if isinstance(legacy_metrics, dict):
        merged = dict(legacy_metrics)
        merged.setdefault("status", metrics["status"])
        merged.setdefault("value_nodes", valued_n)
        merged.setdefault("current_value_nodes", len(current))
        merged.setdefault("previous_value_nodes", len(previous))
        parser = dict(merged.get("parser") or {})
        parser["integration_mode"] = "reuse_completed_canonical"
        parser["source_canonical"] = source_path.name if source_path else None
        merged["parser"] = parser
        return merged
    return metrics


def integrate_financial_position(base: str, output_dir: Path, index: FinancialPositionIndex,
                                 existing_comparison: Optional[dict] = None,
                                 source_text: Optional[str] = None,
                                 current_year: int = 2025, previous_year: int = 2024) -> dict:
    src = index.find(base)
    existing_comparison = existing_comparison or {}
    legacy_fp = existing_comparison.get("financial_position") if isinstance(existing_comparison, dict) else None
    legacy_v05 = legacy_fp.get("v05") if isinstance(legacy_fp, dict) else None

    if src is None:
        # If comparison already embeds FP metrics, preserve them but explicitly report missing canonical artifact.
        if isinstance(legacy_fp, dict):
            return {
                "canonical": None,
                "canonical_file": legacy_fp.get("canonical_file"),
                "metrics": legacy_v05 or {"status": "canonical_artifact_missing"},
                "source_path": None,
                "status": (legacy_v05 or {}).get("status", "canonical_artifact_missing"),
                "preserved_legacy": True,
            }
        return {
            "canonical": None,
            "canonical_file": None,
            "metrics": {
                "status": "financial_position_source_missing",
                "value_nodes": 0,
                "current_value_nodes": 0,
                "previous_value_nodes": 0,
                "mapping": {"canonical_value_nodes": 0, "current_value_nodes": 0, "previous_value_nodes": 0},
                "parser": {"statement_profile": "financial_position", "integration_mode": "missing_source"},
            },
            "source_path": None,
            "status": "financial_position_source_missing",
            "preserved_legacy": False,
        }

    canonical = read_json(src, {})
    canonical = augment_financial_position(canonical)
    recovered = {"rows": [], "scope_start_line": None, "scope_end_line": None, "scope_score": 0}
    if source_text:
        recovered = extract_financial_position_source_rows(source_text, current_year=current_year, previous_year=previous_year)
        canonical = augment_canonical_with_recovered_rows(canonical, recovered.get("rows") or [], "FINANCIAL_POSITION")
        canonical = reconcile_source_observations(canonical, "FINANCIAL_POSITION")
    out_path = output_dir / f"{base}.financial_position.canonical.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    # v13 keeps the historical semantic canonical and adds a reconciled source-observation layer.
    out_path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = summarize_canonical(canonical, src, legacy_metrics=legacy_v05)
    parser = dict(metrics.get("parser") or {})
    parser.update({
        "source_recovery": "v14",
        "recovery_scope_start": recovered.get("scope_start_line"),
        "recovery_scope_end": recovered.get("scope_end_line"),
        "recovery_scope_score": recovered.get("scope_score"),
        "recovered_rows": len(recovered.get("rows") or []),
        "source_recovery_added_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("added_nodes", 0),
        "source_recovery_filled_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("filled_existing_nodes", 0),
        "source_recovery_conflicts": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("conflicts", 0),
    })
    metrics["parser"] = parser
    return {
        "canonical": canonical,
        "canonical_file": out_path.name,
        "metrics": metrics,
        "source_path": src,
        "status": metrics.get("status", "ok"),
        "preserved_legacy": bool(legacy_fp),
    }
