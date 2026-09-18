from __future__ import annotations

import re

from .document import descendants
from .guide import UniversalGuide
from .models import StructuralNode
from .primitives import extract_values, whole_text_period
from .textnorm import fold


ROLE_PAREN_RE = re.compile(r"\(([^()]{1,80})\)")


class StructuralClassifier:
    def __init__(self, guide: UniversalGuide):
        self.guide = guide

    def classify_all(self, nodes: list[StructuralNode]):
        # Pass 1: mẫu leaf/local.
        for node in nodes:
            self._classify_local(node)

        # Pass 2: mẫu parent phụ thuộc vào child.
        for node in reversed(nodes):
            self._upgrade_parent_pattern(node, nodes)

        # Pass 3: lan truyền context kỳ/đơn vị/qualifier.
        for node in nodes:
            self._inherit_context(node, nodes)

    def _set(self, node, pid, score, *evidence):
        node.pattern_id = pid
        node.pattern_name = self.guide.patterns.get(pid, {}).get("name", pid)
        node.pattern_score = score
        node.pattern_evidence = list(evidence)

    def _classify_local(self, node: StructuralNode):
        text = node.text.strip()
        f = fold(text)

        # Context bảng được ưu tiên hơn việc tách pipe chung.
        if node.representation == "table_row":
            self._set(node, "SP_MARKDOWN_TABLE_ROW", 1.0, "table_header_context")
            return

        qualifier = f.rstrip(":")
        if qualifier in self.guide.qualifier_forms:
            node.qualifier = text.rstrip(":").strip()
            self._set(node, "SP_QUALIFIER_CONTAINER", 1.0, "qualifier_lexicon")
            return

        # Bullet chỉ có kỳ mà không có payload là period-container.
        # Nếu cùng dòng đã có giá trị (ví dụ "Năm 2025: -"), nó phải giữ là
        # thuộc tính giá trị kỳ.
        p = whole_text_period(text, node.line_no, self.guide)
        if p and node.is_bullet and not node.values:
            node.periods = [p]
            self._set(node, "SP_PERIOD_CONTAINER", 1.0, "whole_text_period")
            return

        # Dòng pipe không thuộc bảng.
        if "|" in text:
            segments = [x.strip() for x in text.split("|") if x.strip()]
            if len(segments) >= 2:
                self._set(node, "SP_PIPE_DELIMITED_INLINE_ROW", 0.98, "pipe_without_table_context")
                return

        # Dòng báo cáo OCR/LLM compact đã được document parser hydrate:
        # nhãn + mã ba chữ số + [thuyết minh] + hiện tại + trước đây.
        if (
            node.representation in {"plain", "bullet"}
            and node.code
            and re.fullmatch(r"\d{3}", node.code.strip())
            and node.label_text
            and node.values
            and not node.lhs
        ):
            evidence = ["statement_code", f"value_count={len(node.values)}"]
            if node.note:
                evidence.append("note_reference")
            self._set(node, "SP_CODE_NOTE_PERIOD_INLINE_ROW", 0.99, *evidence)
            return

        # Dòng inline nhiều kỳ.
        if len(node.periods) >= 2 and len(node.values) >= 2:
            self._set(node, "SP_MULTI_PERIOD_INLINE", 0.98, "period_count>=2", "value_count>=2")
            return

        lhs_fold = fold(node.lhs or "")
        if node.lhs and lhs_fold in self.guide.named_attribute_keys:
            self._set(node, "SP_NAMED_ATTRIBUTE", 0.98, "named_attribute_lexicon")
            return

        if node.lhs and whole_text_period(node.lhs, node.line_no, self.guide) and node.values:
            self._set(node, "SP_PERIOD_VALUE_ATTRIBUTE", 0.98, "period_lhs", "rhs_value")
            return

        # Dòng chỉ có giá trị, có thể theo sau bởi đơn vị:
        #   195.820.302
        #   195.820.302 (Triệu VND)
        stripped = text.strip()
        values_full = extract_values(stripped, node.line_no, self.guide, mask_periods=True)
        value_only = False
        if node.is_bullet and len(values_full) == 1 and not node.lhs and not node.periods:
            raw_value = values_full[0].raw_value
            if raw_value == stripped:
                value_only = True
            elif node.unit:
                remainder = stripped.replace(node.unit, " ").strip(" ():-")
                value_only = (remainder == raw_value)

        if value_only:
            self._set(node, "SP_VALUE_ONLY_POSITIONAL", 0.95, "whole_text_value_or_value_plus_unit")
            return

        # Bảng OCR/LLM dạng plain thường serialize một dòng tài chính thành:
        #   Nhãn
        #   100
        #   5
        #   58.015.996.839.126
        #   48.680.623.561.824
        # Các dòng chỉ có số trong dạng này là atom dòng theo vị trí dù không
        # phải bullet Markdown. Role semantic (mã/thuyết minh/hiện tại/trước đây)
        # được gán sau bởi collector tuần tự cục bộ.
        if len(values_full) == 1 and not node.lhs and not node.periods:
            raw_value = values_full[0].raw_value
            if raw_value == stripped:
                self._set(node, "SP_VALUE_ONLY_POSITIONAL", 0.90, "plain_whole_text_value")
                return

        if node.lhs and node.values:
            self._set(node, "SP_LABEL_VALUE_INLINE", 0.90, "colon_rhs_value")
            return

        # Context đơn vị/kỳ không phải dòng nghiệp vụ.
        if node.unit and not node.values:
            self._set(node, "SP_CONTEXT_CARRIER", 0.85, "unit_without_value")
            return

        if text:
            self._set(node, "SP_LABEL_CONTAINER", 0.60, "fallback_text")

    def _upgrade_parent_pattern(self, node: StructuralNode, nodes: list[StructuralNode]):
        if not node.children:
            return
        children = [nodes[i] for i in node.children]

        period_children = sum(
            1 for c in children if c.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE"
        )
        value_children = sum(
            1 for c in children if c.pattern_id == "SP_VALUE_ONLY_POSITIONAL"
        )
        keyed_children = sum(
            1 for c in children
            if c.pattern_id in {"SP_NAMED_ATTRIBUTE", "SP_LABEL_VALUE_INLINE"}
        )

        if period_children >= 1 and node.pattern_id in {"SP_LABEL_CONTAINER", "SP_STRUCTURAL_CONTAINER"}:
            self._set(node, "SP_PERIOD_CHILDREN", 0.97, f"period_children={period_children}")
            return

        if value_children >= 2 and node.pattern_id == "SP_LABEL_CONTAINER":
            self._set(node, "SP_POSITIONAL_VALUE_CHILDREN", 0.93, f"value_children={value_children}")
            return

        if keyed_children >= 2 and node.pattern_id == "SP_LABEL_CONTAINER":
            self._set(node, "SP_KEYED_ATTRIBUTE_CHILDREN", 0.88, f"keyed_children={keyed_children}")
            return

        desc = descendants(nodes, node.node_index)
        if (
            node.pattern_id == "SP_LABEL_CONTAINER"
            and any(d.values or d.periods for d in desc)
        ):
            self._set(node, "SP_STRUCTURAL_CONTAINER", 0.75, "descendant_data")

    def _inherit_context(self, node: StructuralNode, nodes: list[StructuralNode]):
        current = node
        seen = set()

        while current.parent_index is not None and current.parent_index not in seen:
            seen.add(current.parent_index)
            parent = nodes[current.parent_index]

            if node.inherited_period is None and parent.pattern_id == "SP_PERIOD_CONTAINER" and parent.periods:
                node.inherited_period = parent.periods[0]

            if node.inherited_unit is None:
                if parent.unit and parent.pattern_id in {"SP_PERIOD_CONTAINER", "SP_CONTEXT_CARRIER"}:
                    node.inherited_unit = parent.unit

            current = parent
