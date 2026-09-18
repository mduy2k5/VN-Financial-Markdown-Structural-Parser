"""Alias-assisted statement location.

The locator is intentionally a *routing* layer.  It does not assign a
canonical value and it does not use statement codes or note references as
identities.  It only ranks source windows before the structural parser runs.

The structural parser remains authoritative for row boundaries, hierarchy,
period columns and semantic mapping.  This separation lets the pipeline use a
large alias catalogue to find a likely statement without turning an alias hit
in a note or a repeated generic label into a mapped value.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import SourceLine
from .preprocess import filter_noise
from .textnorm import fold, normalize_lines, strip_inline_markdown, strip_numbering


@dataclass(frozen=True)
class StatementProfile:
    name: str
    title_patterns: tuple[str, ...]
    signature_anchors: tuple[str, ...]
    stop_patterns: tuple[str, ...]


STATEMENT_PROFILES: dict[str, StatementProfile] = {
    "financial_position": StatementProfile(
        name="financial_position",
        title_patterns=(
            "bao cao tinh hinh tai chinh",
            "bang can doi ke toan",
        ),
        signature_anchors=(
            "tai san",
            "tai san co",
            "no phai tra",
            "von chu so huu",
            "tong cong tai san",
            "tong tai san",
            "tong cong nguon von",
            "tong no phai tra va von chu so huu",
        ),
        stop_patterns=(
            "bao cao ket qua hoat dong",
            "bao cao ket qua kinh doanh",
            "bao cao luu chuyen tien te",
            "ban thuyet minh bao cao tai chinh",
            "thuyet minh bao cao tai chinh",
            "thuyet minh bctc",
        ),
    ),
    "income_statement": StatementProfile(
        name="income_statement",
        title_patterns=(
            "bao cao ket qua hoat dong kinh doanh",
            "bao cao ket qua hoat dong",
            "bao cao ket qua kinh doanh",
        ),
        signature_anchors=(
            "doanh thu ban hang",
            "doanh thu thuan",
            "loi nhuan gop",
            "loi nhuan truoc thue",
            "loi nhuan sau thue",
            "thu nhap lai",
            "chi phi lai",
            "thu nhap lai thuan",
            "lai co ban tren co phieu",
        ),
        stop_patterns=(
            "bao cao luu chuyen tien te",
            "bao cao tinh hinh tai chinh",
            "bang can doi ke toan",
            "ban thuyet minh bao cao tai chinh",
            "thuyet minh bao cao tai chinh",
            "thuyet minh bctc",
        ),
    ),
    "cash_flow": StatementProfile(
        name="cash_flow",
        title_patterns=("bao cao luu chuyen tien te",),
        signature_anchors=(
            "luu chuyen tien thuan tu hoat dong kinh doanh",
            "luu chuyen tien thuan tu hoat dong dau tu",
            "luu chuyen tien thuan tu hoat dong tai chinh",
            "tien va tuong duong tien dau ky",
            "tien va tuong duong tien cuoi ky",
            "tien thu tu ban hang",
            "khau hao tai san co dinh",
        ),
        stop_patterns=(
            "bao cao ket qua hoat dong",
            "bao cao ket qua kinh doanh",
            "bao cao tinh hinh tai chinh",
            "bang can doi ke toan",
            "ban thuyet minh bao cao tai chinh",
            "thuyet minh bao cao tai chinh",
            "thuyet minh bctc",
        ),
    ),
}


@dataclass(frozen=True)
class AliasEntry:
    node_id: str
    alias: str
    normalized: str
    kind: str
    specificity: float


@dataclass
class AliasHit:
    line_no: int
    page_no: int | None
    raw_text: str
    normalized_text: str
    node_id: str
    alias: str
    match_kind: str
    specificity: float
    has_numeric_payload: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateRow:
    line_no: int
    page_no: int | None
    raw_text: str
    matched_node_ids: list[str]
    matched_aliases: list[str]
    has_numeric_payload: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScopeCandidate:
    profile: str
    start_line: int
    end_line: int
    score: float
    confidence: float
    evidence: list[str] = field(default_factory=list)
    alias_hit_count: int = 0
    unique_alias_count: int = 0
    unique_node_count: int = 0
    candidate_row_count: int = 0
    numeric_row_count: int = 0
    period_signal_count: int = 0
    table_signal_count: int = 0
    page_start: int | None = None
    page_end: int | None = None
    title_detected: bool = False
    eligible: bool = False
    candidate_rows: list[CandidateRow] = field(default_factory=list)

    def as_dict(self, *, include_rows: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if not include_rows:
            result.pop("candidate_rows", None)
        else:
            result["candidate_rows"] = [row.as_dict() for row in self.candidate_rows]
        return result


def _clean_for_match(value: Any) -> str:
    text = strip_inline_markdown(str(value or ""))
    text = strip_numbering(text)
    return fold(text)


def _numeric_payload(text: str) -> bool:
    # This is a routing signal only.  It deliberately does not parse values.
    return bool(
        re.search(r"\(?-?\d[\d., ]{2,}\)?", text)
        or re.search(r"\b(?:nam|ky)\s+(?:nay|truoc|nay|truoc)\b", fold(text))
    )


def _is_period_signal(text: str) -> bool:
    f = fold(text)
    return bool(
        re.search(r"\b20\d{2}\b", text)
        or any(x in f for x in ("nam nay", "nam truoc", "ky nay", "ky truoc", "so cuoi nam", "so dau nam"))
    )


def _is_noise_line(text: str) -> bool:
    f = fold(text)
    if not f:
        return True
    if f in {
        "chi tieu", "ma so", "thuyet minh", "nam nay", "nam truoc",
        "ky nay", "ky truoc", "stt", "don vi", "vnd", "dong",
    }:
        return True
    if f.startswith(("metadata", "created at", "updated at", "file name", "s3 key", "search folder")):
        return True
    if re.fullmatch(r"(?:page|trang)\s*\d+(?:\s*[-/]\s*\d+)?", f):
        return True
    return False


def _toc_line_numbers(lines: list[SourceLine], max_span: int = 50) -> set[int]:
    """Return lines belonging to a table-of-contents block.

    A table of contents repeats the exact statement titles and often contains
    more aliases than the real first page.  Treating it as source evidence is
    the most dangerous failure mode for an alias-first locator, so it is
    filtered before scoring.  The boundary is structural (page separator or
    metadata page), not tied to a report name or a fixed page number.
    """

    result: set[int] = set()
    for index, line in enumerate(lines):
        if "muc luc" not in fold(line.clean or line.raw):
            continue
        for following in lines[index : min(len(lines), index + max_span + 1)]:
            text = fold(following.clean or following.raw)
            if following.line_no != line.line_no and (
                text.startswith("# page ")
                or text in {"---", "## metadata", "## content"}
            ):
                break
            result.add(following.line_no)
    return result


def _profile_for(profile: str | StatementProfile) -> StatementProfile:
    if isinstance(profile, StatementProfile):
        return profile
    try:
        return STATEMENT_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown statement profile: {profile}") from exc


def _schema_names(schema_path: str | Path | None) -> dict[str, str]:
    if not schema_path:
        return {}
    try:
        document = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(node.get("node_id")): str(node.get("canonical_name") or node.get("node_id"))
        for node in document.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }


def _alias_entries(
    aliases_path: str | Path | None,
    *,
    schema_path: str | Path | None = None,
) -> list[AliasEntry]:
    if not aliases_path:
        return []
    try:
        document = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    names = _schema_names(schema_path)
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        # B02/B03 alias packs are flat maps: node_id -> [aliases].
        nodes = document if isinstance(document, dict) else {}

    entries: list[AliasEntry] = []
    seen: set[tuple[str, str, str]] = set()
    for node_id, raw_spec in nodes.items():
        if not isinstance(node_id, str):
            continue
        if node_id in {"alias_schema_version", "target_schema", "normalization", "matching_priority", "ambiguity_policy"}:
            continue
        if isinstance(raw_spec, dict):
            match = raw_spec.get("match") or raw_spec
            values_by_kind = {
                "canonical": [names.get(node_id) or raw_spec.get("canonical_name")],
                "exact": match.get("exact") or [],
                "alias": match.get("aliases") or [],
                "contains": match.get("contains") or [],
            }
        elif isinstance(raw_spec, list):
            values_by_kind = {"alias": raw_spec}
        else:
            continue

        for kind, values in values_by_kind.items():
            if isinstance(values, str):
                values = [values]
            for value in values:
                normalized = _clean_for_match(value)
                if len(normalized) < 4:
                    continue
                if normalized in {"chi tieu", "ma so", "thuyet minh", "nam nay", "nam truoc", "tong cong"}:
                    continue
                key = (node_id, normalized, kind)
                if key in seen:
                    continue
                seen.add(key)
                token_count = len(normalized.split())
                specificity = min(1.0, 0.35 + token_count * 0.12)
                if kind == "contains":
                    specificity *= 0.82
                entries.append(AliasEntry(node_id, str(value), normalized, kind, specificity))
    return entries


class StatementLocator:
    """Locate a statement using aliases and cheap structural evidence.

    The class is reusable for all three main statements.  It does not need a
    report name, issuer symbol, form code or previous output.  Profile-specific
    titles/signatures and the alias pack are the only semantic configuration.
    """

    def __init__(
        self,
        *,
        aliases_path: str | Path | None = None,
        schema_path: str | Path | None = None,
        max_cluster_gap: int = 42,
        context_before: int = 12,
        context_after: int = 24,
        min_confidence: float = 0.72,
    ):
        self.aliases_path = str(aliases_path) if aliases_path else None
        self.schema_path = str(schema_path) if schema_path else None
        self.entries = _alias_entries(aliases_path, schema_path=schema_path)
        self.max_cluster_gap = max(1, int(max_cluster_gap))
        self.context_before = max(0, int(context_before))
        self.context_after = max(0, int(context_after))
        self.min_confidence = float(min_confidence)

    def _hits(self, lines: list[SourceLine]) -> list[AliasHit]:
        hits: list[AliasHit] = []
        toc_lines = _toc_line_numbers(lines)
        # Index entries by first token so the scan remains cheap even for the
        # largest alias catalogues.  Matching still uses normalized phrases.
        by_first: dict[str, list[AliasEntry]] = {}
        for entry in self.entries:
            by_first.setdefault(entry.normalized.split()[0], []).append(entry)

        for line in lines:
            raw = line.clean or line.raw or ""
            normalized = _clean_for_match(raw)
            if line.line_no in toc_lines or _is_noise_line(raw) or not normalized:
                continue
            padded = f" {normalized} "
            first_tokens = set(normalized.split())
            matched: set[tuple[str, str]] = set()
            for token in first_tokens:
                for entry in by_first.get(token, []):
                    needle = f" {entry.normalized} "
                    if needle not in padded:
                        continue
                    key = (entry.node_id, entry.normalized)
                    if key in matched:
                        continue
                    matched.add(key)
                    hits.append(AliasHit(
                        line_no=line.line_no,
                        page_no=line.page_no,
                        raw_text=raw,
                        normalized_text=normalized,
                        node_id=entry.node_id,
                        alias=entry.alias,
                        match_kind=entry.kind,
                        specificity=entry.specificity,
                        has_numeric_payload=_numeric_payload(raw),
                    ))
        return hits

    @staticmethod
    def _primary_lines(lines: list[SourceLine]) -> list[SourceLine]:
        """Exclude the notes body from the cheap alias scan.

        Main statements are structurally before the notes section in the
        source format.  Notes repeat many primary-statement labels, so scanning
        them adds cost and creates false candidate clusters without improving
        statement routing.  The boundary is detected from the source text and
        is not tied to page count, issuer or filename.
        """

        note_patterns = (
            "ban thuyet minh bao cao tai chinh",
            "thuyet minh bao cao tai chinh",
            "thuyet minh bctc",
        )
        toc_lines = _toc_line_numbers(lines)
        for index, line in enumerate(lines):
            normalized = _clean_for_match(line.clean or line.raw)
            if line.line_no in toc_lines:
                continue
            if len(normalized) <= 180 and any(normalized.startswith(pattern) for pattern in note_patterns):
                return lines[:index]
        return lines

    @staticmethod
    def _title(
        line: SourceLine,
        profile: StatementProfile,
        *,
        toc_lines: set[int] | None = None,
    ) -> bool:
        if toc_lines and line.line_no in toc_lines:
            return False
        text = _clean_for_match(line.clean or line.raw)
        return any(text.startswith(pattern) for pattern in profile.title_patterns)

    @staticmethod
    def _stop(line: SourceLine, profile: StatementProfile) -> bool:
        text = _clean_for_match(line.clean or line.raw)
        return any(text.startswith(pattern) for pattern in profile.stop_patterns)

    def _candidate_starts(
        self,
        lines: list[SourceLine],
        hits: list[AliasHit],
        profile: StatementProfile,
    ) -> list[int]:
        toc_lines = _toc_line_numbers(lines)
        title_lines = [
            line.line_no
            for line in lines
            if self._title(line, profile, toc_lines=toc_lines)
        ]
        # When a real statement heading exists, it is the only structural
        # start candidate we need to score.  Alias clusters are still scanned
        # and scored inside that window.  Cluster starts are used only for
        # heading-less/OCR documents; this prevents the locator from doing a
        # quadratic full-document score for every repeated alias in notes.
        starts = list(title_lines)
        hit_lines = sorted({hit.line_no for hit in hits})
        if hit_lines and not title_lines:
            cluster_start = hit_lines[0]
            previous = hit_lines[0]
            for line_no in hit_lines[1:]:
                if line_no - previous > self.max_cluster_gap:
                    starts.append(cluster_start)
                    cluster_start = line_no
            previous = line_no
            starts.append(cluster_start)
        # If an alias cluster starts in the metadata immediately before a real
        # heading, use the heading as the scope start.  This keeps the locator
        # from treating metadata as part of a statement while preserving the
        # useful cluster as supporting evidence.
        aligned: list[int] = []
        for start in starts:
            nearby_titles = [
                title for title in title_lines
                if abs(title - start) <= self.context_before
            ]
            aligned.append(min(nearby_titles, key=lambda title: abs(title - start)) if nearby_titles else start)
        return sorted(set(aligned))

    def _end_for(
        self,
        lines: list[SourceLine],
        start_line: int,
        profile: StatementProfile,
    ) -> int:
        last_line = lines[-1].line_no if lines else start_line
        for line in lines:
            if line.line_no <= start_line:
                continue
            if self._stop(line, profile):
                return max(start_line, line.line_no - 1)
        return last_line

    def _score(
        self,
        lines: list[SourceLine],
        hits: list[AliasHit],
        start_line: int,
        end_line: int,
        profile: StatementProfile,
    ) -> ScopeCandidate:
        selected_lines = [line for line in lines if start_line <= line.line_no <= end_line]
        selected_hits = [hit for hit in hits if start_line <= hit.line_no <= end_line]
        toc_lines = _toc_line_numbers(lines)
        title_detected = any(
            self._title(line, profile, toc_lines=toc_lines)
            for line in selected_lines[: max(1, self.context_before + 3)]
        )
        unique_aliases = {fold(hit.alias) for hit in selected_hits}
        unique_nodes = {hit.node_id for hit in selected_hits}
        numeric_rows = sum(1 for line in selected_lines if _numeric_payload(line.clean or line.raw))
        period_signals = sum(1 for line in selected_lines if _is_period_signal(line.clean or line.raw))
        table_signals = sum(1 for line in selected_lines if (line.clean or "").count("|") >= 2)
        signature_hits = [
            anchor for anchor in profile.signature_anchors
            if any(anchor in _clean_for_match(line.clean or line.raw) for line in selected_lines)
        ]

        rows_by_line: dict[int, CandidateRow] = {}
        for hit in selected_hits:
            row = rows_by_line.setdefault(
                hit.line_no,
                CandidateRow(
                    line_no=hit.line_no,
                    page_no=hit.page_no,
                    raw_text=hit.raw_text,
                    matched_node_ids=[],
                    matched_aliases=[],
                    has_numeric_payload=hit.has_numeric_payload,
                ),
            )
            if hit.node_id not in row.matched_node_ids:
                row.matched_node_ids.append(hit.node_id)
            if hit.alias not in row.matched_aliases:
                row.matched_aliases.append(hit.alias)
            row.has_numeric_payload = row.has_numeric_payload or hit.has_numeric_payload

        # The score is intentionally evidence-based and bounded.  It ranks
        # candidate windows; it is not a semantic mapping confidence.
        score = 0.0
        evidence: list[str] = []
        if title_detected:
            score += 4.0
            evidence.append("statement_title:+4")
        if unique_nodes:
            value = min(6.0, len(unique_nodes) * 0.75)
            score += value
            evidence.append(f"unique_alias_nodes:{len(unique_nodes)}:+{value:g}")
        if unique_aliases:
            value = min(3.0, len(unique_aliases) * 0.18)
            score += value
            evidence.append(f"unique_aliases:{len(unique_aliases)}:+{value:g}")
        if signature_hits:
            value = min(4.0, len(signature_hits) * 0.65)
            score += value
            evidence.append(f"signature_hits:{len(signature_hits)}:+{value:g}")
        if numeric_rows:
            value = min(3.0, numeric_rows * 0.12)
            score += value
            evidence.append(f"numeric_rows:{numeric_rows}:+{value:g}")
        if period_signals:
            value = min(2.0, period_signals * 0.12)
            score += value
            evidence.append(f"period_signals:{period_signals}:+{value:g}")
        if table_signals:
            value = min(1.5, table_signals * 0.18)
            score += value
            evidence.append(f"table_signals:{table_signals}:+{value:g}")

        # Normalize the routing confidence by evidence capacity rather than
        # by a report-specific expected row count.
        confidence = min(
            0.995,
            0.30
            + (0.20 if title_detected else 0.0)
            + min(0.30, len(unique_nodes) * 0.04)
            + min(0.12, len(signature_hits) * 0.02)
            + min(0.08, len(rows_by_line) * 0.008),
        )
        eligible = bool(
            confidence >= self.min_confidence
            and len(unique_nodes) >= 3
            and len(rows_by_line) >= 2
            and (title_detected or len(unique_nodes) >= 5)
        )
        if not eligible:
            evidence.append("fallback_required")

        pages = [line.page_no for line in selected_lines if line.page_no is not None]
        return ScopeCandidate(
            profile=profile.name,
            start_line=start_line,
            end_line=end_line,
            score=round(score, 4),
            confidence=round(confidence, 4),
            evidence=evidence,
            alias_hit_count=len(selected_hits),
            unique_alias_count=len(unique_aliases),
            unique_node_count=len(unique_nodes),
            candidate_row_count=len(rows_by_line),
            numeric_row_count=numeric_rows,
            period_signal_count=period_signals,
            table_signal_count=table_signals,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            title_detected=title_detected,
            eligible=eligible,
            candidate_rows=list(rows_by_line.values()),
        )

    @staticmethod
    def evaluate_scope(
        locator_result: dict[str, Any] | None,
        baseline_start: int,
        baseline_end: int,
        *,
        min_overlap_ratio: float = 0.80,
        max_start_delta: int = 48,
        max_end_delta: int = 160,
        min_confidence: float = 0.72,
    ) -> tuple[bool, str]:
        """Check whether a located scope is safe to route into a parser.

        The same gate is shared by B01, B02 and B03.  It prevents a valid alias
        cluster in a note from widening or replacing an existing structural
        scope when the two pieces of evidence disagree.
        """

        locator_result = locator_result or {}
        selected = locator_result.get("selected_scope") or {}
        if not selected:
            return False, "no_selected_scope"
        candidates = locator_result.get("candidates") or []
        chosen = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("start_line") == selected.get("start_line")
                and candidate.get("end_line") == selected.get("end_line")
            ),
            {},
        )
        if not chosen.get("title_detected"):
            return False, "candidate_not_title_backed"

        locator_start = int(selected.get("start_line") or 0)
        locator_end = int(selected.get("end_line") or 0)
        if locator_start <= 0 or locator_end < locator_start:
            return False, "invalid_selected_scope"

        baseline_span = max(1, baseline_end - baseline_start + 1)
        locator_span = max(1, locator_end - locator_start + 1)
        overlap = max(0, min(baseline_end, locator_end) - max(baseline_start, locator_start) + 1)
        overlap_ratio = overlap / max(baseline_span, locator_span)
        start_delta = abs(locator_start - baseline_start)
        end_delta = abs(locator_end - baseline_end)

        if overlap_ratio < min_overlap_ratio:
            return False, f"scope_overlap_too_low:{overlap_ratio:.3f}"
        if start_delta > max_start_delta:
            return False, f"scope_start_delta_too_large:{start_delta}"
        if end_delta > max_end_delta:
            return False, f"scope_end_delta_too_large:{end_delta}"
        if float(selected.get("confidence") or 0.0) < min_confidence:
            return False, "locator_confidence_below_threshold"
        return True, "title_backed_scope_overlap"

    def locate(self, raw_text: str, *, profile: str | StatementProfile) -> dict[str, Any]:
        profile_obj = _profile_for(profile)
        raw_lines = normalize_lines(raw_text or "")
        lines = filter_noise(raw_lines)
        scan_lines = self._primary_lines(lines)
        hits = self._hits(scan_lines)
        starts = self._candidate_starts(scan_lines, hits, profile_obj)

        candidates: list[ScopeCandidate] = []
        toc_lines = _toc_line_numbers(lines)
        for start in starts:
            end = self._end_for(lines, start, profile_obj)
            # Alias clusters without a title are narrowed to their local
            # evidence block; titled statements retain the full continuation
            # range up to the next statement boundary.
            if not any(
                self._title(line, profile_obj, toc_lines=toc_lines)
                for line in lines
                if line.line_no == start
            ):
                local_hits = [hit for hit in hits if start <= hit.line_no <= end]
                if local_hits:
                    end = min(end, max(hit.line_no for hit in local_hits) + self.context_after)
                    start = max(lines[0].line_no if lines else start, start - self.context_before)
            candidate = self._score(scan_lines, hits, start, end, profile_obj)
            candidates.append(candidate)

        candidates.sort(key=lambda item: (item.score, item.confidence, -item.start_line), reverse=True)
        selected = candidates[0] if candidates else None
        selected_scope = None
        if selected and selected.eligible:
            selected_scope = {
                "start_line": selected.start_line,
                "end_line": selected.end_line,
                "confidence": selected.confidence,
                "score": selected.score,
                "page_start": selected.page_start,
                "page_end": selected.page_end,
            }

        return {
            "profile": profile_obj.name,
            "mode": "alias_assisted_locator",
            "aliases_path": self.aliases_path,
            "schema_path": self.schema_path,
            "line_count": len(lines),
            "scan_line_count": len(scan_lines),
            "alias_catalog_size": len(self.entries),
            "alias_hit_count": len(hits),
            "candidate_count": len(candidates),
            "selected_scope": selected_scope,
            "fallback_used": selected_scope is None,
            "candidate_rows": [row.as_dict() for row in (selected.candidate_rows if selected else [])],
            "candidates": [candidate.as_dict(include_rows=False) for candidate in candidates],
        }


def locator_for_profile(
    profile: str,
    *,
    schema_path: str | Path | None = None,
    aliases_path: str | Path | None = None,
) -> StatementLocator:
    """Small factory used by the three statement engines."""

    # Keep the profile argument in the factory API so callers can construct
    # profile-specific locators without report-specific branches.  The current
    # locator object shares the same generic scanning implementation.
    _profile_for(profile)
    return StatementLocator(schema_path=schema_path, aliases_path=aliases_path)
