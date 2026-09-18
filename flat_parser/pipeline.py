from __future__ import annotations

from pathlib import Path

from .alias_matcher import choose_candidate
from .mapping_strategy import match_candidates_for_strategy
from .canonical_mapper import map_first_value_per_period
from .consolidator import consolidate_resolved_fields
from .dual_role import expand_dual_role_rows
from .validator import validate_financial_position
from .collector import collect_observation
from .context import detect_context, financial_position_scope
from .document import build_nodes, hydrate_keyed_record_wrappers, hydrate_column_major_statement_blocks
from .guide import UniversalGuide
from .models import jsonable
from .preprocess import filter_noise
from .resolver import resolve_observation
from .semantic_catalog import SemanticCatalog
from .source_context import source_context_for_node
from .statement_locator import StatementLocator
from .structural_classifier import StructuralClassifier
from .tables import detect_tables
from .textnorm import normalize_lines, fold
from .qa import analyze_semantic_coverage, canonical_completeness, detect_explicit_totals, detect_sector
from .version import PARSER_VERSION


class FlatParserPipeline:
    def __init__(
        self,
        *,
        schema_path,
        aliases_path,
        universal_guide_path,
        allow_fuzzy=False,
        scope_mode="financial_position",
        allow_unknown_structure=False,
        mapping_strategy="legacy",
        enable_locator=True,
        locator_min_confidence=0.72,
    ):
        self.catalog = SemanticCatalog(schema_path, aliases_path)
        self.guide = UniversalGuide(universal_guide_path)
        self.classifier = StructuralClassifier(self.guide)
        self.allow_fuzzy = allow_fuzzy
        self.scope_mode = scope_mode
        self.allow_unknown_structure = allow_unknown_structure
        self.mapping_strategy = mapping_strategy
        self.enable_locator = bool(enable_locator)
        self.locator = (
            StatementLocator(
                schema_path=schema_path,
                aliases_path=aliases_path,
                min_confidence=locator_min_confidence,
            )
            if self.enable_locator
            else None
        )

    @staticmethod
    def _accept_locator_scope(
        baseline_start: int,
        baseline_end: int,
        locator_debug: dict,
    ) -> tuple[bool, str]:
        """Accept only a nearby, title-backed locator result.

        The locator is a routing optimization, not a reason to widen a
        statement into notes.  A title-backed candidate must substantially
        overlap the existing structural scope and may move the boundaries only
        within bounded structural context.  Otherwise the established scope
        detector remains authoritative.
        """

        return StatementLocator.evaluate_scope(
            locator_debug,
            baseline_start,
            baseline_end,
        )

    def parse_text(
        self,
        raw_text: str,
        source_name="input",
        *,
        scope_override: tuple[int, int] | None = None,
        detected_sector_override: str | None = None,
        statement_profile: str = "financial_position",
    ):
        raw_lines = normalize_lines(raw_text)
        lines = filter_noise(raw_lines)

        locator_debug = None
        if self.locator is not None and statement_profile in {
            "financial_position",
            "income_statement",
            "cash_flow",
        }:
            locator_debug = self.locator.locate(
                raw_text,
                profile=statement_profile,
            )

        if scope_override is not None:
            scope_start, scope_end = scope_override
            scope_debug = {
                "mode": "statement_scanner_override",
                "selected_start": scope_start,
                "selected_end": scope_end,
                "candidates": [],
                "health": "scanner_routed",
                "statement_profile": statement_profile,
            }
        else:
            scope_result = financial_position_scope(lines, self.scope_mode)
            if len(scope_result) == 3:
                scope_start, scope_end, scope_debug = scope_result
            else:
                scope_start, scope_end = scope_result
                scope_debug = {
                    "mode": self.scope_mode,
                    "selected_start": scope_start,
                    "selected_end": scope_end,
                    "candidates": [],
                }

            if locator_debug is not None:
                accepted, locator_reason = self._accept_locator_scope(
                    scope_start,
                    scope_end,
                    locator_debug,
                )
                locator_debug["activation"] = {
                    "activated": accepted,
                    "reason": locator_reason,
                    "baseline_start": scope_start,
                    "baseline_end": scope_end,
                }
                if accepted:
                    selected = locator_debug["selected_scope"]
                    baseline = {
                        "start_line": scope_start,
                        "end_line": scope_end,
                        "mode": scope_debug.get("mode"),
                    }
                    scope_start = int(selected["start_line"])
                    scope_end = int(selected["end_line"])
                    scope_debug = {
                        "mode": "alias_assisted_locator",
                        "selected_start": scope_start,
                        "selected_end": scope_end,
                        "baseline": baseline,
                        "locator": locator_debug,
                        "health": "locator_routed",
                    }
                else:
                    scope_debug = dict(scope_debug)
                    scope_debug["locator"] = locator_debug

        scoped = [x for x in lines if scope_start <= x.line_no <= scope_end]

        context = detect_context(lines, self.guide, scope_start, scope_end)
        tables, table_line_map = detect_tables(scoped)
        nodes = build_nodes(scoped, table_line_map, self.guide)
        hydrate_keyed_record_wrappers(nodes)
        self.classifier.classify_all(nodes)

        column_major_log = hydrate_column_major_statement_blocks(nodes, self.guide)
        if column_major_log:
            self.classifier.classify_all(nodes)

        # Scope health must be explicit in QA. "unresolved=0" is not success
        # when scope detection produced only one structural node.
        scope_health = scope_debug.get("health", "unknown")
        if len(nodes) <= 3:
            scope_health = "critical_tiny_scope"
        elif len(nodes) < 10:
            scope_health = "suspicious_small_scope"

        scope_debug["post_build_health"] = scope_health
        scope_debug["post_build_structural_nodes"] = len(nodes)

        observations = []
        resolved = []
        unresolved = []
        ignored_non_errors = []

        # ----------------------------------------------------------
        # PASS 1: semantic anchor discovery only.
        # This determines where each canonical record begins.
        # ----------------------------------------------------------
        prior_selected = []
        anchor_selection = {}
        semantic_anchor_indices = set()

        # Detect sector before alias matching so sector-specific nodes cannot
        # leak across bank / enterprise / securities / insurance contexts.
        sector_qa = detect_sector("\n".join(x.clean for x in scoped), self.catalog)
        if detected_sector_override:
            sector_qa = dict(sector_qa)
            sector_qa["detected_sector"] = detected_sector_override
            schema_sectors = sector_qa.get("schema_sectors") or []
            sector_qa["schema_sector_gap"] = (
                None if detected_sector_override in schema_sectors else detected_sector_override
            )
            sector_qa.setdefault("evidence", []).append("statement_scanner_sector_override")

        for node in nodes:
            if not node.label_text:
                continue

            candidates = match_candidates_for_strategy(
                self.mapping_strategy,
                node,
                nodes,
                self.catalog,
                prior_selected,
                allow_fuzzy=self.allow_fuzzy,
                detected_sector=sector_qa.get("detected_sector"),
            )
            if not candidates:
                continue

            selected, reason = choose_candidate(candidates)
            anchor_selection[node.node_index] = {
                "candidates": candidates,
                "selected": selected,
                "reason": reason,
            }

            if selected is not None:
                semantic_anchor_indices.add(node.node_index)
                prior_selected.append(
                    (node.line_no, selected.node_id, node.label_text)
                )

        semantic_coverage = analyze_semantic_coverage(
            nodes, anchor_selection, semantic_anchor_indices,
            detected_sector=sector_qa.get("detected_sector"),
        )

        # ----------------------------------------------------------
        # PASS 2: collect payload bounded by semantic child anchors.
        # ----------------------------------------------------------
        for node in nodes:
            selection = anchor_selection.get(node.node_index)
            if not selection:
                continue

            candidates = selection["candidates"]
            selected = selection["selected"]
            reason = selection["reason"]

            if selected is None:
                unresolved.append({
                    "line_no": node.line_no,
                    "source_label": node.label_text,
                    "reason": reason,
                    "pattern_id": node.pattern_id,
                    "candidates": jsonable(candidates[:8]),
                })
                continue

            obs = collect_observation(
                node,
                nodes,
                selected,
                candidates,
                self.guide,
                semantic_anchor_indices=semantic_anchor_indices,
            )
            observations.append(obs)

            field, error = resolve_observation(
                obs,
                context,
                allow_structure_unknown=self.allow_unknown_structure,
                source_context=source_context_for_node(
                    node,
                    nodes,
                    prior_selected=prior_selected,
                    catalog=self.catalog,
                ),
            )
            if field is None:
                unresolved.append({
                    "line_no": node.line_no,
                    "source_label": node.label_text,
                    "selected_node_id": selected.node_id,
                    "reason": error,
                    "pattern_id": node.pattern_id,
                    "pattern_name": node.pattern_name,
                    "observation": jsonable(obs),
                })
            else:
                resolved.append(field)

        # Reclassify no-payload cases that are not extraction failures.
        # 1) another occurrence of the same node already resolved successfully;
        # 2) source record contains only code/note attributes and no financial
        #    value.  Keep these in QA metadata but not in unresolved errors.
        resolved_node_ids = {f.node_id for f in resolved}

        def _has_financial_payload_descendant(node):
            queue = list(node.children)
            seen = set()
            depth = 0
            while queue and depth < 40:
                idx = queue.pop(0)
                depth += 1
                if idx in seen:
                    continue
                seen.add(idx)
                d = nodes[idx]
                key = fold(d.lhs or "")
                if key in {"ma so", "code", "thuyet minh", "so lieu thuyet minh", "chi tieu"}:
                    queue.extend(d.children)
                    continue
                if d.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE" and d.values:
                    return True
                if d.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and d.values:
                    return True
                if d.inherited_period and d.values:
                    return True
                queue.extend(d.children)
            return False

        kept_unresolved = []
        for item in unresolved:
            if item.get("reason") != "no_payload":
                kept_unresolved.append(item)
                continue

            selected_id = item.get("selected_node_id")
            node_index = None
            obs = item.get("observation") or {}
            node_index = obs.get("anchor_node_index")

            if selected_id in resolved_node_ids:
                item = dict(item)
                item["classification"] = "duplicate_no_payload"
                ignored_non_errors.append(item)
                continue

            source_has_values = False
            if isinstance(node_index, int) and 0 <= node_index < len(nodes):
                anchor_node = nodes[node_index]

                # A repeated same-label semantic child is a common structural
                # wrapper: the parent row has no source value while the child
                # carries the actual current/previous payload. Do not report
                # the wrapper as an extraction failure (EIB-like layout).
                same_label_semantic_child = any(
                    child_idx in semantic_anchor_indices
                    and fold(nodes[child_idx].label_text or nodes[child_idx].text)
                        == fold(anchor_node.label_text or anchor_node.text)
                    for child_idx in anchor_node.children
                )
                if same_label_semantic_child:
                    item = dict(item)
                    item["classification"] = "structural_wrapper_no_value"
                    ignored_non_errors.append(item)
                    continue

                source_has_values = _has_financial_payload_descendant(anchor_node)

            if not source_has_values:
                item = dict(item)
                item["classification"] = "source_no_value"
                ignored_non_errors.append(item)
                continue

            kept_unresolved.append(item)

        unresolved = kept_unresolved

        # Consolidate structural continuations before final collision protection.
        consolidated, consolidation_log = consolidate_resolved_fields(
            resolved,
            context,
        )

        # Expand dual-role enterprise section/total rows only for the balance sheet.
        # OFF_BALANCE has its own group/value semantics and must not inherit B02
        # section/total synthesis rules.
        if statement_profile == "financial_position":
            expanded, dual_role_log = expand_dual_role_rows(
                consolidated,
                self.catalog,
            )
        else:
            expanded = consolidated
            dual_role_log = []

        canonical, accepted, dedup_log = map_first_value_per_period(
            expanded,
            self.catalog,
        )

        if statement_profile == "financial_position":
            validation = validate_financial_position(canonical)
            explicit_totals = detect_explicit_totals(
                lines, scope_start, scope_end, self.guide
            )
            completeness = canonical_completeness(canonical, explicit_totals)
        else:
            # OFF_BALANCE is point-in-time disclosure data and is deliberately
            # excluded from Assets = Liabilities + Equity validation.
            validation = {
                "checks": [],
                "passed": 0,
                "failed": 0,
                "classification": "not_applicable_off_balance",
            }
            explicit_totals = {"detected": [], "count": 0}
            completeness = {
                "explicit_total_missed": 0,
                "classification": "not_applicable_off_balance",
            }

        canonical_nodes = {n["node_id"]: n for n in canonical.get("nodes", [])}
        value_nodes = [
            n for n in canonical.get("nodes", [])
            if any(n.get("value", {}).get(k) is not None for k in ("current", "previous"))
        ]
        current_value_nodes = sum(
            1 for n in value_nodes if n.get("value", {}).get("current") is not None
        )
        previous_value_nodes = sum(
            1 for n in value_nodes if n.get("value", {}).get("previous") is not None
        )

        total_assets_present = canonical_nodes.get("TOTAL_ASSETS", {}).get("value", {}).get("current") is not None
        total_source_present = canonical_nodes.get("TOTAL_LIABILITIES_AND_EQUITY", {}).get("value", {}).get("current") is not None

        if statement_profile == "off_balance":
            if not value_nodes and not resolved:
                statement_health = "critical_no_financial_values"
            elif unresolved:
                statement_health = "review_required"
            elif current_value_nodes >= 3 and previous_value_nodes == 0:
                statement_health = "suspicious_single_period_only"
            elif sector_qa.get("schema_sector_gap"):
                statement_health = f"schema_sector_gap:{sector_qa['schema_sector_gap']}"
            else:
                statement_health = "healthy"
        elif completeness.get("explicit_total_missed", 0) > 0:
            statement_health = "critical_explicit_total_missed"
        elif not value_nodes:
            statement_health = "critical_no_financial_values"
        elif not total_assets_present and not total_source_present:
            statement_health = "critical_missing_statement_totals"
        elif current_value_nodes >= 5 and previous_value_nodes == 0:
            statement_health = "suspicious_single_period_only"
        elif validation.get("failed", 0) > 0:
            if validation.get("classification") == "source_balance_inconsistent":
                statement_health = "source_balance_inconsistent"
            else:
                statement_health = "critical_balance_validation_failed"
        elif sector_qa.get("schema_sector_gap"):
            statement_health = f"schema_sector_gap:{sector_qa['schema_sector_gap']}"
        else:
            # Semantic coverage is a ranking/QA metric, not a hard health gate:
            # the denominator still varies across serialization families.
            statement_health = "healthy"

        semantic_dedup = (canonical.get("diagnostics") or {}).get("semantic_dedup") or {}
        semantic_dedup_conflicts = int(semantic_dedup.get("conflict_count") or 0)
        if semantic_dedup_conflicts:
            statement_health = "review_required"

        stats = {
            "source_name": source_name,
            "parser_version": PARSER_VERSION,
            "statement_profile": statement_profile,
            "schema_nodes": len(self.catalog.nodes),
            "scope_mode": self.scope_mode,
            "scope_start": scope_start,
            "scope_end": scope_end,
            "scope_health": scope_health,
            "locator_enabled": self.enable_locator,
            "locator_activated": bool((locator_debug or {}).get("activation", {}).get("activated")),
            "locator_confidence": ((locator_debug or {}).get("selected_scope") or {}).get("confidence"),
            "locator_alias_hits": (locator_debug or {}).get("alias_hit_count", 0),
            "locator_candidate_rows": len((locator_debug or {}).get("candidate_rows") or []),
            "statement_health": statement_health,
            "value_nodes": len(value_nodes),
            "current_value_nodes": current_value_nodes,
            "previous_value_nodes": previous_value_nodes,
            "table_blocks": len(tables),
            "structural_nodes": len(nodes),
            "semantic_anchors": len(semantic_anchor_indices),
            "alias_observations": len(observations),
            "resolved_before_dedup": len(resolved),
            "resolved_after_consolidation": len(consolidated),
            "resolved_after_dual_role": len(expanded),
            "accepted_occurrences": len(accepted),
            "unresolved": len(unresolved),
            "ignored_non_errors": len(ignored_non_errors),
            "column_major_hydrated": len(column_major_log),
            "financial_label_candidates": semantic_coverage.get("financial_label_candidates"),
            "matched_financial_labels": semantic_coverage.get("matched_financial_labels"),
            "unknown_financial_labels": semantic_coverage.get("unknown_financial_labels"),
            "actionable_unknown_financial_labels": semantic_coverage.get("actionable_unknown_financial_labels"),
            "actionable_financial_label_candidates": semantic_coverage.get("actionable_financial_label_candidates"),
            "ambiguous_financial_labels": semantic_coverage.get("ambiguous_financial_labels"),
            "semantic_label_coverage": semantic_coverage.get("semantic_label_coverage"),
            "actionable_semantic_label_coverage": semantic_coverage.get("actionable_semantic_label_coverage"),
            "raw_unknown_financial_labels": semantic_coverage.get("raw_unknown_financial_labels"),
            "noise_unknown_financial_labels": semantic_coverage.get("noise_unknown_financial_labels"),
            "off_balance_unknown_financial_labels": semantic_coverage.get("off_balance_unknown_financial_labels"),
            "sector_schema_unknown_financial_labels": semantic_coverage.get("sector_schema_unknown_financial_labels"),
            "semantic_unknown_financial_labels": semantic_coverage.get("semantic_unknown_financial_labels"),
            "generic_review_financial_labels": semantic_coverage.get("generic_review_financial_labels"),
            "structural_gap_financial_labels": semantic_coverage.get("structural_gap_financial_labels"),
            "true_actionable_unknown_financial_labels": semantic_coverage.get("true_actionable_unknown_financial_labels"),
            "true_actionable_financial_label_candidates": semantic_coverage.get("true_actionable_financial_label_candidates"),
            "true_actionable_semantic_label_coverage": semantic_coverage.get("true_actionable_semantic_label_coverage"),
            "unknown_classification_counts": semantic_coverage.get("unknown_classification_counts"),
            "unknown_top_labels": semantic_coverage.get("unknown_top_labels"),
            "semantic_coverage_review_recommended": (
                semantic_coverage.get("semantic_label_coverage") is not None
                and semantic_coverage.get("semantic_label_coverage") < 0.45
            ),
            "detected_sector": sector_qa.get("detected_sector"),
            "schema_sector_gap": sector_qa.get("schema_sector_gap"),
            "explicit_total_missed": completeness.get("explicit_total_missed"),
            "resolved_ratio_over_semantic_anchors": (
                round(len(resolved) / len(semantic_anchor_indices), 6)
                if semantic_anchor_indices else None
            ),
            "dedup_policy": "first_value_per_period_wins_with_conflict_audit",
            "semantic_dedup_conflicts": semantic_dedup_conflicts,
            "collector_policy": "semantic_child_boundaries",
            "fuzzy_enabled": self.allow_fuzzy,
            "unknown_structure_allowed": self.allow_unknown_structure,
        }

        return {
            "canonical": canonical,
            "debug": {
                "stats": stats,
                "scope_debug": scope_debug,
                "locator": locator_debug,
                "context": jsonable(context),
                "tables": jsonable(tables),
                "nodes": jsonable(nodes),
                "semantic_anchor_indices": sorted(semantic_anchor_indices),
                "observations": jsonable(observations),
                "resolved_before_dedup": jsonable(resolved),
                "consolidation_log": consolidation_log,
                "dual_role_log": dual_role_log,
                "column_major_log": column_major_log,
                "validation": validation,
                "semantic_coverage": semantic_coverage,
                "sector_qa": sector_qa,
                "explicit_totals": explicit_totals,
                "completeness": completeness,
                "dedup_log": dedup_log,
                "unresolved": unresolved,
                "ignored_non_errors": ignored_non_errors,
            },
        }

    def parse_file(self, path):
        path = Path(path)
        return self.parse_text(
            path.read_text(encoding="utf-8-sig"),
            source_name=path.name,
        )
