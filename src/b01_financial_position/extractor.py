from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from src.common.source_observation import augment_financial_position
    from src.common.source_recovery import extract_financial_position_source_rows, augment_canonical_with_recovered_rows
    from src.common.source_reconciler import reconcile_source_observations
    from src.common.period_resolver import repair_financial_position_period_identity
    from src.common.report_period import resolve_report_years
except ImportError:
    from source_observation import augment_financial_position
    from source_recovery import extract_financial_position_source_rows, augment_canonical_with_recovered_rows
    from source_reconciler import reconcile_source_observations
    from period_resolver import repair_financial_position_period_identity
    from report_period import resolve_report_years


FP_CANONICAL_SUFFIX = ".financial_position.canonical.json"
GENERIC_CANONICAL_SUFFIX = ".canonical.json"
EXCLUDE_CANONICAL_MARKERS = (".income.canonical.json", ".cashflow.canonical.json")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def stem_base(path: Path) -> str:
    name = path.stem
    return re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)


def canonical_base_name(path: Path) -> str:
    name = path.name
    if name.endswith(FP_CANONICAL_SUFFIX):
        name = name[: -len(FP_CANONICAL_SUFFIX)]
    elif name.endswith(GENERIC_CANONICAL_SUFFIX):
        name = name[: -len(GENERIC_CANONICAL_SUFFIX)]
    name = re.sub(r"\((?:\d+|\d{8}-\d{6})\)$", "", name)
    return name


def _source_provenance(obj: dict) -> tuple[Optional[str], Optional[str]]:
    provenance = obj.get("provenance") if isinstance(obj.get("provenance"), dict) else {}
    source_name = obj.get("source_name") or provenance.get("source_name")
    source_sha256 = obj.get("source_sha256") or provenance.get("source_sha256")
    return (
        str(source_name) if source_name else None,
        str(source_sha256).lower() if source_sha256 else None,
    )


def has_source_provenance(obj: dict) -> bool:
    source_name, source_sha256 = _source_provenance(obj)
    return bool(
        source_name
        and source_sha256
        and re.fullmatch(r"[0-9a-f]{64}", source_sha256)
    )


def is_financial_position_canonical(path: Path, *, require_provenance: bool = True) -> bool:
    low = path.name.lower()
    if not low.endswith(FP_CANONICAL_SUFFIX) and not low.endswith(GENERIC_CANONICAL_SUFFIX):
        return False
    if low.endswith(GENERIC_CANONICAL_SUFFIX) and any(low.endswith(x) for x in EXCLUDE_CANONICAL_MARKERS):
        return False
    obj = read_json(path, {})
    if not (
        isinstance(obj, dict)
        and obj.get("statement_type") == "FINANCIAL_POSITION"
        and obj.get("schema_id") == "UNIVERSAL_FINANCIAL_POSITION_V1"
    ):
        return False
    return not require_provenance or has_source_provenance(obj)


class FinancialPositionArtifactError(ValueError):
    """Raised when a persisted B01 artifact is not safe to reuse."""


class FinancialPositionArtifactAmbiguityError(FinancialPositionArtifactError):
    """Raised when more than one valid artifact claims the same report."""


@dataclass
class FinancialPositionIndex:
    by_base: dict[str, Path]
    scanned_files: int = 0
    duplicates: dict[str, tuple[Path, ...]] = field(default_factory=dict)

    @classmethod
    def build(cls, roots: Iterable[Path], *, require_provenance: bool = True) -> "FinancialPositionIndex":
        candidates_by_base: dict[str, list[Path]] = {}
        scanned = 0
        seen_roots = set()
        seen_files = set()
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
                try:
                    file_key = p.resolve()
                except Exception:
                    file_key = p
                if file_key in seen_files:
                    continue
                seen_files.add(file_key)
                scanned += 1
                if not is_financial_position_canonical(p, require_provenance=require_provenance):
                    continue
                base = canonical_base_name(p)
                candidates_by_base.setdefault(base, []).append(p)

        by_base: dict[str, Path] = {}
        duplicates: dict[str, tuple[Path, ...]] = {}
        for base, candidates in candidates_by_base.items():
            if len(candidates) == 1:
                by_base[base] = candidates[0]
            else:
                duplicates[base] = tuple(sorted(candidates, key=lambda x: str(x)))
        return cls(by_base=by_base, scanned_files=scanned, duplicates=duplicates)

    def find(self, base: str) -> Optional[Path]:
        if base in self.duplicates:
            candidates = ", ".join(str(x) for x in self.duplicates[base])
            raise FinancialPositionArtifactAmbiguityError(
                f"Multiple valid Financial Position artifacts for {base}: {candidates}"
            )
        return self.by_base.get(base)


def validate_financial_position_artifact(
    path: Path,
    *,
    expected_source_name: Optional[str] = None,
    expected_source_sha256: Optional[str] = None,
    expected_current_year: Optional[int] = None,
    expected_previous_year: Optional[int] = None,
) -> dict:
    """Load and validate a persisted B01 artifact against its source identity."""
    obj = read_json(path, None)
    if not isinstance(obj, dict) or not is_financial_position_canonical(path, require_provenance=True):
        raise FinancialPositionArtifactError(
            f"Invalid or unverified Financial Position artifact: {path}"
        )
    source_name, source_sha256 = _source_provenance(obj)
    if expected_source_name and source_name != expected_source_name:
        raise FinancialPositionArtifactError(
            f"Financial Position artifact source mismatch for {path.name}: "
            f"expected {expected_source_name!r}, got {source_name!r}"
        )
    if expected_source_sha256 and source_sha256 != expected_source_sha256.lower():
        raise FinancialPositionArtifactError(
            f"Financial Position artifact hash mismatch for {path.name}"
        )
    provenance = obj.get("provenance") if isinstance(obj.get("provenance"), dict) else {}
    for key, expected in (
        ("current_year", expected_current_year),
        ("previous_year", expected_previous_year),
    ):
        if expected is not None and provenance.get(key) != expected:
            raise FinancialPositionArtifactError(
                f"Financial Position artifact {key} mismatch for {path.name}: "
                f"expected {expected}, got {provenance.get(key)!r}"
            )
    return obj


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


def _attach_source_provenance(
    canonical: dict,
    *,
    source_name: str,
    source_sha256: str,
    current_year: int | None,
    previous_year: int | None,
    year_resolution: Optional[dict[str, Any]] = None,
) -> dict:
    canonical["source_name"] = source_name
    canonical["source_sha256"] = source_sha256
    canonical["provenance"] = {
        "source_name": source_name,
        "source_sha256": source_sha256,
        "current_year": current_year,
        "previous_year": previous_year,
    }
    if year_resolution:
        canonical["provenance"]["year_resolution"] = year_resolution
    return canonical


def _set_statement_unit(canonical: dict, unit: Optional[str]) -> dict:
    if not unit or unit == "unknown":
        return canonical
    canonical["unit"] = unit
    for node in canonical.get("nodes", []):
        value = node.get("value")
        if (
            isinstance(value, dict)
            and value.get("unit") is None
            and (value.get("current") is not None or value.get("previous") is not None)
        ):
            value["unit"] = unit
    return canonical


def summarize_canonical(
    canonical: dict,
    source_path: Optional[Path] = None,
    *,
    integration_mode: str = "validated_artifact",
) -> dict:
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
            "integration_mode": integration_mode,
            "source_canonical": source_path.name if source_path else None,
        },
    }
    return metrics


class FinancialPositionSourceParser:
    """Parse B01 directly from Markdown without reading prior report output."""

    def __init__(
        self,
        *,
        schema_path: Optional[Path] = None,
        aliases_path: Optional[Path] = None,
        guide_path: Optional[Path] = None,
    ):
        # Import lazily so artifact-index users do not need to initialize the
        # structural parser unless source-only mode is actually requested.
        from flat_parser.pipeline import FlatParserPipeline

        project_root = Path(__file__).resolve().parents[2]
        self.parser = FlatParserPipeline(
            schema_path=schema_path or project_root / "resources" / "universal_financial_position_schema_v1_6.json",
            aliases_path=aliases_path or project_root / "resources" / "universal_financial_position_aliases_v1_6_1.json",
            universal_guide_path=guide_path or project_root / "resources" / "universal_structural_guide_a1_a5.json",
            scope_mode="financial_position",
            mapping_strategy="legacy",
        )

    def parse_text(
        self,
        source_text: str,
        *,
        source_name: str,
        source_sha256: Optional[str] = None,
        current_year: int | None = None,
        previous_year: int | None = None,
        fallback_unit: Optional[str] = None,
    ) -> dict:
        period = resolve_report_years(
            source_text,
            source_name=source_name,
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
        source_sha256 = source_sha256 or hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        result = self.parser.parse_text(
            source_text,
            source_name=source_name,
            statement_profile="financial_position",
        )
        canonical = result.get("canonical") if isinstance(result, dict) else None
        debug = result.get("debug") if isinstance(result, dict) else {}
        debug = debug if isinstance(debug, dict) else {}
        raw_stats = debug.get("stats") if isinstance(debug.get("stats"), dict) else {}
        if not isinstance(canonical, dict):
            return {
                "canonical": None,
                "canonical_file": None,
                "metrics": {
                    "status": "financial_position_source_missing",
                    "value_nodes": 0,
                    "current_value_nodes": 0,
                    "previous_value_nodes": 0,
                    "mapping": {
                        "canonical_value_nodes": 0,
                        "current_value_nodes": 0,
                        "previous_value_nodes": 0,
                    },
                    "parser": {
                        "statement_profile": "financial_position",
                        "integration_mode": "source_parse",
                        "source_name": source_name,
                        "source_sha256": source_sha256,
                    },
                },
                "source_path": None,
                "status": "financial_position_source_missing",
                "preserved_legacy": False,
                "scope": debug.get("scope_debug") or {},
                "sector": raw_stats.get("detected_sector") or "unknown",
            }

        recovered = extract_financial_position_source_rows(
            source_text,
            current_year=current_year,
            previous_year=previous_year,
            fallback_unit=fallback_unit,
        )
        stmt_unit = fallback_unit if fallback_unit and fallback_unit != "unknown" else None
        rec_unit = recovered.get("unit")
        if rec_unit and rec_unit != "unknown":
            stmt_unit = rec_unit
        canonical = augment_canonical_with_recovered_rows(
            canonical,
            recovered.get("rows") or [],
            "FINANCIAL_POSITION",
        )
        canonical = reconcile_source_observations(canonical, "FINANCIAL_POSITION")
        canonical = _set_statement_unit(canonical, stmt_unit)
        canonical = _attach_source_provenance(
            canonical,
            source_name=source_name,
            source_sha256=source_sha256,
            current_year=current_year,
            previous_year=previous_year,
            year_resolution=period,
        )

        metrics = summarize_canonical(canonical, integration_mode="source_parse")
        parser_metrics = dict(metrics.get("parser") or {})
        parser_metrics.update({
            "source_name": source_name,
            "source_sha256": source_sha256,
            "source_parser_version": raw_stats.get("parser_version"),
            "source_recovery": "v16.1",
            "recovery_scope_start": recovered.get("scope_start_line"),
            "recovery_scope_end": recovered.get("scope_end_line"),
            "recovery_scope_score": recovered.get("scope_score"),
            "recovered_rows": len(recovered.get("rows") or []),
            "source_recovery_added_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("added_nodes", 0),
            "source_recovery_filled_nodes": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("filled_existing_nodes", 0),
            "source_recovery_conflicts": ((canonical.get("diagnostics") or {}).get("source_statement_recovery") or {}).get("conflicts", 0),
            "source_statement_health": raw_stats.get("statement_health"),
            "source_scope_health": raw_stats.get("scope_health"),
        })
        metrics["parser"] = parser_metrics
        return {
            "canonical": canonical,
            "canonical_file": None,
            "metrics": metrics,
            "source_path": None,
            "status": metrics.get("status", "ok"),
            "preserved_legacy": False,
            "scope": debug.get("scope_debug") or {},
            "sector": raw_stats.get("detected_sector") or "unknown",
        }


def integrate_financial_position(base: str, output_dir: Path, index: FinancialPositionIndex,
                                 existing_comparison: Optional[dict] = None,
                                 source_text: Optional[str] = None,
                                 current_year: int | None = None, previous_year: int | None = None,
                                 fallback_unit: Optional[str] = None,
                                 expected_source_name: Optional[str] = None,
                                 expected_source_sha256: Optional[str] = None,
                                 expected_current_year: Optional[int] = None,
                                 expected_previous_year: Optional[int] = None) -> dict:
    """Reuse only an explicitly supplied, provenance-validated B01 artifact.

    ``existing_comparison`` is retained as a compatibility argument but is
    deliberately ignored. Previous comparison metrics must never restore a
    missing current-run statement.
    """
    src = index.find(base)

    if src is None:
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

    canonical = validate_financial_position_artifact(
        src,
        expected_source_name=expected_source_name,
        expected_source_sha256=expected_source_sha256,
        expected_current_year=expected_current_year,
        expected_previous_year=expected_previous_year,
    )
    if source_text and (current_year is None or previous_year is None):
        period = resolve_report_years(
            source_text,
            source_name=expected_source_name or f"{base}.md",
            current_year=current_year,
            previous_year=previous_year,
        )
        current_year = period["current_year"]
        previous_year = period["previous_year"]
    provenance = canonical.get("provenance") if isinstance(canonical.get("provenance"), dict) else {}
    current_year = current_year if current_year is not None else provenance.get("current_year")
    previous_year = previous_year if previous_year is not None else provenance.get("previous_year")
    canonical = augment_financial_position(canonical)
    # v16.1: repair period identity from explicit source period labels before additive source recovery.
    canonical = repair_financial_position_period_identity(canonical, current_year=current_year, previous_year=previous_year)
    recovered = {"rows": [], "scope_start_line": None, "scope_end_line": None, "scope_score": 0}
    stmt_unit = fallback_unit if fallback_unit and fallback_unit != "unknown" else None
    if source_text:
        recovered = extract_financial_position_source_rows(source_text, current_year=current_year, previous_year=previous_year, fallback_unit=fallback_unit)
        rec_unit = recovered.get("unit")
        if rec_unit and rec_unit != "unknown":
            stmt_unit = rec_unit
        canonical = augment_canonical_with_recovered_rows(canonical, recovered.get("rows") or [], "FINANCIAL_POSITION")
        canonical = reconcile_source_observations(canonical, "FINANCIAL_POSITION")

    canonical = _set_statement_unit(canonical, stmt_unit)

    out_path = output_dir / f"{base}.financial_position.canonical.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    # v16 keeps the historical semantic canonical and adds a reconciled source-observation layer.
    out_path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = summarize_canonical(canonical, src, integration_mode="validated_artifact")
    parser = dict(metrics.get("parser") or {})
    parser.update({
        "source_name": canonical.get("source_name"),
        "source_sha256": canonical.get("source_sha256"),
        "source_recovery": "v16.1",
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
        "preserved_legacy": False,
    }
