from __future__ import annotations

import re

from .document import descendants
from .guide import UniversalGuide
from .models import StructuralNode
from .primitives import extract_periods, extract_values, whole_text_period
from .textnorm import fold


ROLE_PAREN_RE = re.compile(r"\(([^()]{1,80})\)")


def _standalone_period_heading(
    text: str,
    line_no: int,
    guide: UniversalGuide,
):
    """Nhận diện tiêu đề kỳ có hậu tố trình bày lại/ghi chú hình thức."""

    period = whole_text_period(text, line_no, guide)
    if period is not None:
        return period

    periods = extract_periods(text, line_no, guide)
    if len(periods) != 1:
        return None

    remainder = text.replace(periods[0].raw_period, " ")
    remainder = re.sub(r"[*_`]+", " ", remainder)
    remainder = remainder.strip(" ():-").strip()
    if fold(remainder) in {
        "trinh bay lai",
        "restated",
        "reclassified",
        "recast",
    }:
        return periods[0]
    return None


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

        # Pass 4: một số nguồn period-major không tạo quan hệ cây giữa tiêu đề
        # kỳ và block dữ liệu kế tiếp. Ví dụ Markdown có dạng:
        #
        #   **31/12/2025**
        #   * TÀI SẢN
        #       * ...: giá trị
        #   **01/01/2025**
        #   * TÀI SẢN
        #       * ...: giá trị
        #
        # Hai dòng ``TÀI SẢN`` đều ở cùng mức indent với tiêu đề kỳ, nên pass 3
        # không thể truyền period qua parent. Giữ period hiện hành theo thứ tự
        # nguồn để các record có payload nhận đúng kỳ; record đã có period hoặc
        # đã nhận được period từ cây vẫn được ưu tiên.
        self._inherit_sequential_period_context(nodes)

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

        # Dòng chỉ có kỳ mà không có payload là period-container.  Nguồn OCR/
        # Markdown thường bỏ dấu bullet ở tiêu đề kỳ (ví dụ ``31/12/2025`` và
        # ``01/01/2025`` đứng riêng trên một dòng), vì vậy không được giới hạn
        # rule này cho bullet. Nếu cùng dòng đã có giá trị (ví dụ
        # ``Năm 2025: -``), nó phải giữ là thuộc tính giá trị kỳ.
        p = _standalone_period_heading(text, node.line_no, self.guide)
        if p and not node.values:
            node.periods = [p]
            evidence = ["whole_text_period"]
            if not node.is_bullet:
                evidence.append("standalone_period_heading")
            self._set(node, "SP_PERIOD_CONTAINER", 1.0, *evidence)
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

            # Nhiều báo cáo đặt tổng kỳ ở một dòng wrapper có cả kỳ và giá
            # trị, sau đó đặt các dòng chi tiết bên dưới nhưng không lặp lại
            # nhãn kỳ. Ví dụ:
            #
            #   31/12/2025: tổng
            #       Chi tiết: giá trị
            #
            # Trước đây chỉ ``SP_PERIOD_CONTAINER`` truyền được kỳ xuống
            # child. Khi wrapper là ``SP_PERIOD_VALUE_ATTRIBUTE`` hoặc một
            # dòng period-value tương đương, child bị resolve theo vị trí và
            # thường rơi cả vào kỳ hiện tại. Đây là nguyên nhân chính của
            # semantic duplicate ở VIB/VCB. Chỉ truyền từ node thực sự có
            # period, không suy đoán từ nhãn tài chính bất kỳ.
            if (
                node.inherited_period is None
                and parent.periods
                and (
                    parent.pattern_id == "SP_PERIOD_CONTAINER"
                    or parent.pattern_id == "SP_CONTEXT_CARRIER"
                    or (
                        parent.values
                        and parent.pattern_id in {
                            "SP_PERIOD_VALUE_ATTRIBUTE",
                            "SP_LABEL_VALUE_INLINE",
                            "SP_MULTI_PERIOD_INLINE",
                            "SP_CODE_NOTE_PERIOD_INLINE_ROW",
                            "SP_MARKDOWN_TABLE_ROW",
                        }
                    )
                )
            ):
                node.inherited_period = parent.periods[0]

            if node.inherited_unit is None:
                if parent.unit and (
                    parent.pattern_id in {
                        "SP_PERIOD_CONTAINER",
                        "SP_PERIOD_VALUE_ATTRIBUTE",
                        "SP_LABEL_VALUE_INLINE",
                        "SP_MULTI_PERIOD_INLINE",
                        "SP_CODE_NOTE_PERIOD_INLINE_ROW",
                        "SP_MARKDOWN_TABLE_ROW",
                        "SP_CONTEXT_CARRIER",
                    }
                ):
                    node.inherited_unit = parent.unit

            current = parent

    def _inherit_sequential_period_context(self, nodes: list[StructuralNode]):
        active_period = None
        period_heading_indices = [
            node.node_index
            for node in nodes
            if node.pattern_id == "SP_PERIOD_CONTAINER" and node.periods
        ]
        # Hai ngày nằm sát nhau thường là header cột (kỳ hiện tại/kỳ trước),
        # không phải hai block dữ liệu nối tiếp. Những header này không được
        # dùng để gán một kỳ cho toàn bộ các dòng ``Số liệu`` phía sau.
        paired_header_indices = {
            index
            for left, right in zip(period_heading_indices, period_heading_indices[1:])
            if nodes[right].line_no - nodes[left].line_no <= 2
            for index in (left, right)
        }

        for node in nodes:
            if node.pattern_id == "SP_PERIOD_CONTAINER" and node.periods:
                candidate = node.periods[0]
                # ``Năm 2025``/``Năm 2024`` thường là header chung của các
                # dòng có hai giá trị theo vị trí, không phải hai block dữ liệu
                # nối tiếp. Chỉ dùng tiêu đề có ngày cụ thể làm ranh giới
                # period-major; đây là bằng chứng đủ mạnh để đổi toàn bộ block
                # tiếp theo sang kỳ mới.
                raw_period = fold(candidate.raw_period or "")
                if node.node_index in paired_header_indices:
                    active_period = None
                elif re.search(
                    r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b"
                    r"|\bngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+20\d{2}\b",
                    raw_period,
                ):
                    active_period = candidate
                continue

            if (
                active_period is not None
                and not node.periods
                and len(node.values) == 1
                and node.inherited_period is None
            ):
                node.inherited_period = active_period
