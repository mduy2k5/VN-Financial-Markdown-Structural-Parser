from __future__ import annotations

import re

from .guide import UniversalGuide
from .models import FieldObservation, StructuralNode
from .primitives import extract_periods, extract_values, whole_text_period
from .textnorm import fold


CODE_KEYS = {"ma so", "code"}
NOTE_KEYS = {"thuyet minh", "so lieu thuyet minh"}


def _period_value_pairs(periods, values):
    """Ghép các giá trị số với nhãn kỳ thực tế.

    Một số dòng bị làm phẳng có token role chung (ví dụ ``năm nay``) trước hai
    ngày rõ ràng. Đây là metadata, không phải cột giá trị thứ ba, nên khi có
    token thừa thì ưu tiên các kỳ ngày ở cuối.
    """

    periods = list(periods or [])
    values = list(values or [])
    if len(periods) > len(values) and values:
        explicit = [
            period
            for period in periods
            if re.search(
                r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b20\d{2}\b",
                period.raw_period or "",
            )
        ]
        if len(explicit) >= len(values):
            periods = explicit[-len(values):]
    return list(zip(periods[:len(values)], values[:len(periods)]))


def _parse_pipe_inline(node: StructuralNode, guide: UniversalGuide):
    text = node.text
    segments = [x.strip() for x in text.split("|")]

    first_segment = segments[0]
    if ":" in first_segment:
        _, first_data = first_segment.split(":", 1)
        data_segments = [first_data.strip()] + segments[1:]
    else:
        data_segments = segments[1:]

    values = []
    period_values = []
    code = None
    note = None
    numeric_values = []

    for segment in data_segments:
        if not segment:
            continue

        vals = extract_values(segment, node.line_no, guide, mask_periods=True)
        periods = extract_periods(segment, node.line_no, guide)
        role_m = re.search(r"\(([^()]+)\)", segment)
        explicit_role = role_m.group(1).strip() if role_m else None

        if periods and vals:
            vals[0].role = explicit_role or periods[0].role
            period_values.append((periods[0], vals[0]))
            continue

        if vals:
            vals[0].role = explicit_role
            numeric_values.extend(vals)

    # Dòng BCTC thường gặp: nhãn | mã | thuyết minh/rỗng | hiện tại | trước đây.
    if len(numeric_values) >= 3:
        first = numeric_values[0]
        if (
            first.role is None
            and first.normalized_candidate is not None
            and first.normalized_candidate == first.normalized_candidate.to_integral()
            and 0 <= first.normalized_candidate < 1000
            and len(first.raw_value.strip("()")) <= 3
        ):
            code = first.raw_value
            numeric_values = numeric_values[1:]

    values = numeric_values
    return values, period_values, code, note


def _bounded_descendants(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    semantic_anchor_indices: set[int],
    max_depth: int = 6,
):
    """
    Duyệt descendant nhưng KHÔNG đi qua record semantic khác.

    Nếu descendant B đã là anchor canonical được alias giải quyết, B và subtree
    của nó thuộc về B, không thuộc A. Đây là quy tắc ranh giới cốt lõi v0.4.2.
    """
    out = []
    queue = [(idx, 1) for idx in anchor.children]
    semantic_boundary_seen = False

    while queue:
        idx, depth = queue.pop(0)
        if depth > max_depth:
            continue

        node = nodes[idx]

        if idx in semantic_anchor_indices:
            # Ranh giới child semantic: không lấy child và không đi vào subtree.
            #
            # Một lỗi Markdown lặp lại gắn payload của child vào parent trong
            # cây thụt lề. Khi gặp child semantic đầu tiên, mọi sibling sau đó
            # trong lượt duyệt giới hạn thuộc child đó (hoặc child sau), không
            # thuộc parent. Vẫn giữ payload trước child vì đó thường là dòng
            # tổng của chính parent.
            semantic_boundary_seen = True
            continue

        if semantic_boundary_seen:
            # Không để liên kết sibling hỏng đưa payload của child quay lại qua
            # wrapper thuyết minh/giá trị sau ranh giới.
            continue

        # Dòng có nhãn và giá trị nhưng chưa phải anchor semantic vẫn là record
        # nguồn thật. Không gộp nó vào tổng nhóm trước chỉ vì cây Markdown gắn
        # cả hai dòng vào cùng parent. Loại nhãn chỉ có ngày vì chúng thường là
        # cột giá trị tách rời; giữ chúng cho caller audit mơ hồ thay vì âm thầm bỏ.
        record_label = (node.label_text or "").strip()
        record_boundary = (
            node.parent_index == anchor.node_index
            and bool(record_label)
            and bool(node.values)
            and bool(node.periods)
            and node.pattern_id in {
                "SP_MULTI_PERIOD_INLINE",
                "SP_PIPE_DELIMITED_INLINE_ROW",
                "SP_MARKDOWN_TABLE_ROW",
                "SP_CODE_NOTE_PERIOD_INLINE_ROW",
                "SP_LABEL_VALUE_INLINE",
            }
            and fold(record_label) not in {
                "tong", "tong cong", "total", "tong so",
            }
            and not fold(record_label).startswith((
                "so cuoi nam",
                "so dau nam",
                "ngay ",
                "nam nay",
                "nam truoc",
            ))
            and not re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}\b", record_label)
        )
        if record_boundary:
            semantic_boundary_seen = True
            continue

        # Báo cáo trộn plain/bullet thường có một container dòng hợp lệ nhưng
        # chưa map giữa tổng section và dòng chi tiết. Cũng xem container cấu
        # trúc đó là ranh giới; nếu không tổng section sẽ nhận mọi giá trị con
        # và trông như bị lặp.
        keyed_wrapper = fold(node.lhs or "") in {
            "ten chi tieu",
            "ten khoan muc",
            "khoan muc",
            "chi tieu",
        }
        if (
            node.children
            and not keyed_wrapper
            and not node.lhs
            and node.pattern_id in {
                "SP_PERIOD_CHILDREN",
                "SP_POSITIONAL_VALUE_CHILDREN",
                "SP_KEYED_ATTRIBUTE_CHILDREN",
            }
        ):
            continue

        out.append(node)

        for child_idx in node.children:
            queue.append((child_idx, depth + 1))

    return out



def _sequential_local_attributes(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    semantic_anchor_indices: set[int],
    guide: UniversalGuide,
    max_nodes: int = 8,
):
    """
    Fallback cho dạng serialize Markdown như:

        **TỔNG TÀI SẢN**
        * Số cuối năm: ...
        * Số đầu năm: ...

    Nhãn plain/in đậm không phải parent bullet nên cây thụt lề không có quan hệ.
    Chỉ quét các node cục bộ ngay sau và dừng ở anchor semantic kế tiếp hoặc
    node nghiệp vụ không liên quan.
    """
    period_values = []
    note = None
    code = None
    unit = None
    positional_atoms = []

    start = anchor.node_index + 1
    end = min(len(nodes), start + max_nodes)

    for i in range(start, end):
        n = nodes[i]

        # Ngắt trang/nhảy cấu trúc lớn là ranh giới cứng.
        if n.line_no - anchor.line_no > 8:
            break

        if i in semantic_anchor_indices:
            break

        if n.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
            p = whole_text_period(n.lhs or "", n.line_no, guide)
            if p and n.values:
                period_values.append((p, n.values[0]))
                unit = unit or n.unit or n.inherited_unit
                continue

        # Thuộc tính cục bộ có ngày, ví dụ:
        #   Số liệu ngày 31/12/2025 (VND): 86...
        # Không cần phân loại thành SP_PERIOD_VALUE_ATTRIBUTE nếu có đúng một
        # kỳ báo cáo và một giá trị.
        if n.values and len(n.values) == 1:
            ps = extract_periods(n.lhs or n.text or "", n.line_no, guide)
            if len(ps) == 1:
                period_values.append((ps[0], n.values[0]))
                unit = unit or n.unit or n.inherited_unit
                continue

        if (
            n.pattern_id == "SP_LABEL_VALUE_INLINE"
            and n.lhs
            and fold(n.lhs) in {"tong", "tong cong", "total", "tong so"}
            and n.values
        ):
            positional_atoms.extend(n.values)
            unit = unit or n.unit or n.inherited_unit
            continue

        if n.pattern_id == "SP_NAMED_ATTRIBUTE" and n.lhs:
            key = fold(n.lhs)
            if key in NOTE_KEYS:
                note = note or (n.rhs.strip() if n.rhs else None)
                continue
            if key in CODE_KEYS:
                code = code or (n.rhs.strip() if n.rhs else None)
                continue

        # Dạng serialize wrapper:
        #   C - NỢ PHẢI TRẢ
        #   * Chỉ tiêu: 300
        #       * Số cuối năm: ...
        #       * Số đầu năm: ...
        if n.lhs and fold(n.lhs) in {"chi tieu", "ma so", "code"}:
            if n.rhs:
                code = code or n.rhs.strip()
            for child_idx in n.children:
                child = nodes[child_idx]
                if child.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
                    p = whole_text_period(child.lhs or "", child.line_no, guide)
                    if p and child.values:
                        period_values.append((p, child.values[0]))
                        unit = unit or child.unit or child.inherited_unit
            if period_values:
                continue

        # Công thức hiển thị như "(270=100+200)" / "(440 = 300 + 400)" là
        # metadata cấu trúc, không phải payload tài chính và không nên kết thúc
        # record cục bộ.
        formula_text = (n.text or "").strip().strip("()")
        if re.fullmatch(r"\d{2,3}\s*=\s*\d{2,3}(?:\s*[+\-]\s*\d{2,3})+", formula_text):
            continue

        if n.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and n.values:
            positional_atoms.extend(n.values)
            unit = unit or n.unit or n.inherited_unit
            continue

        # Node không phải thuộc tính khác sẽ kết thúc record cục bộ.
        break

    # Gói dòng tuần tự plain. Đọc từ đuôi vì giá trị tài chính là hai atom cuối,
    # còn atom đầu thường là mã biểu mẫu và tham chiếu thuyết minh tùy chọn. Ví dụ:
    #   nhãn / 100 / hiện tại / trước đây
    #   nhãn / 110 / 5 / hiện tại / trước đây
    # Mã/thuyết minh chỉ là metadata và không bao giờ là khóa mapping.
    positional_values = []
    if not period_values and len(positional_atoms) >= 2:
        atoms = list(positional_atoms)
        if len(atoms) >= 3:
            prefix = atoms[:-2]
            positional_values = atoms[-2:]
            if prefix:
                first = prefix[0]
                raw = first.raw_value.strip()
                if re.fullmatch(r"\d{2,3}(?:\.\d+)?", raw):
                    code = code or raw
                elif re.fullmatch(r"\d+(?:\.\d+)+", raw):
                    note = note or raw
            if len(prefix) >= 2:
                raw = prefix[1].raw_value.strip()
                if re.fullmatch(r"\d+(?:\.\d+)*", raw):
                    note = note or raw
        else:
            positional_values = atoms[:2]

    # Giữ thứ tự cột theo vị trí từ header rõ gần đó.
    # Một số output OCR serialize "Số đầu năm" trước "Số cuối năm".
    if not period_values and len(positional_values) == 2:
        recent_periods = []
        for prev in nodes[max(0, anchor.node_index - 140):anchor.node_index]:
            f = fold(prev.text or "")
            if not any(k in f for k in ("so dau nam", "so cuoi nam", "dau nam", "cuoi nam")):
                continue
            pp = whole_text_period(prev.text or "", prev.line_no, guide)
            if pp:
                recent_periods.append(pp)
        if len(recent_periods) >= 2:
            pair = recent_periods[-2:]
            folded = [fold(x.raw_period) for x in pair]
            if any("dau nam" in x for x in folded) and any("cuoi nam" in x for x in folded):
                period_values = list(zip(pair, positional_values))
                positional_values = []

    return period_values, note, code, unit, positional_values


DETACHED_TOTAL_NODE_IDS = {
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "TOTAL_EQUITY",
    "TOTAL_LIABILITIES_AND_EQUITY",
}


def _recover_detached_total_payload(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    selected,
):
    """
    Khôi phục payload khi nhãn tổng tài chính bị tách khỏi giá trị.

    Các dạng cấu trúc chung được hỗ trợ:

    1) Heading + payload nhiều kỳ tách rời
       TỔNG NỢ + VỐN
       1,192... (2025), 978... (2024)

    2) Heading + giá trị có key chung
       TỔNG TÀI SẢN
       Số liệu: hiện tại
       Số liệu (Trình bày lại): trước đây

    3) Heading + block bảng Markdown không có nhãn theo sau
       TỔNG TÀI SẢN
       | ...header kỳ... |
       | chi tiết ... |
       | GIÁ TRỊ TỔNG HIỆN TẠI | GIÁ TRỊ TỔNG TRƯỚC ĐÂY |

       Khi tiêu đề tổng đứng trước một block bảng tách rời, tổng là dòng cuối
       của block, không nhất thiết là dòng gần nhất. Dạng này thường gặp khi
       OCR/LLM serialize nhãn trước ma trận giá trị.

    Trả về (period_values, positional_values, unit, evidence) hoặc None.
    """
    if selected.node_id not in DETACHED_TOTAL_NODE_IDS:
        return None

    start = anchor.node_index + 1
    lookahead = nodes[start:min(len(nodes), start + 80)]
    if not lookahead:
        return None

    # Bỏ dấu phân cách/nhiễu số trang nhưng vẫn giữ phạm vi cục bộ.
    def is_noise(n: StructuralNode):
        f = fold(n.text or "")
        if f in {"---", "—", "-", ""}:
            return True
        if re.fullmatch(r"\d{1,3}", (n.text or "").strip()):
            return True
        return False

    nearby = []
    for n in lookahead:
        if n.line_no - anchor.line_no > 40:
            break
        nearby.append(n)

    # ---------------------------------------------------------------
    # Dạng 1: payload nhiều kỳ độc lập trực tiếp.
    # ---------------------------------------------------------------
    for n in nearby[:5]:
        if is_noise(n):
            continue
        if (
            n.pattern_id == "SP_MULTI_PERIOD_INLINE"
            and len(n.periods) >= 2
            and len(n.values) >= 2
        ):
            return (
                list(zip(n.periods[:2], n.values[:2])),
                [],
                n.unit or n.inherited_unit,
                "detached_total_multi_period",
            )
        # Nhãn có vẻ semantic nhưng không liên quan sẽ kết thúc dạng trực tiếp.
        if n.label_text and n.pattern_id not in {
            "SP_VALUE_ONLY_POSITIONAL",
            "SP_LABEL_VALUE_INLINE",
        }:
            break

    # ---------------------------------------------------------------
    # Dạng 2: hai giá trị có khóa chung ngay sau dòng tổng.
    # Cố ý giữ theo vị trí. Resolver sẽ map giá trị đầu/thứ hai theo context
    # hiện tại/trước đây của báo cáo.
    # ---------------------------------------------------------------
    keyed = []
    keyed_unit = None
    for n in nearby[:6]:
        if is_noise(n):
            continue
        if (
            n.pattern_id == "SP_LABEL_VALUE_INLINE"
            and n.lhs
            and n.values
            and fold(n.lhs).startswith(("so lieu", "gia tri"))
        ):
            keyed.append(n.values[0])
            keyed_unit = keyed_unit or n.unit or n.inherited_unit
            if len(keyed) == 2:
                return ([], keyed, keyed_unit, "detached_total_generic_keyed_pair")
            continue
        if keyed:
            break
        if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
            break
        if n.label_text and n.pattern_id != "SP_VALUE_ONLY_POSITIONAL":
            break

    # ---------------------------------------------------------------
    # Dạng 3: block bảng tách rời.
    # Dòng bảng đầu phải nằm gần về vật lý với tiêu đề tổng. Khi block bắt đầu,
    # dùng dòng cuối có hai giá trị kỳ; cách này tránh hành vi "dòng gần nhất"
    # không an toàn.
    # ---------------------------------------------------------------
    table_rows = []
    started = False

    # QUAN TRỌNG: khoảng cách dòng chỉ là cổng cho ĐIỂM BẮT ĐẦU của bảng tách rời.
    # Khi bảng bắt đầu, lấy toàn bộ block liên tục. Không dùng lại cửa sổ gần
    # 40 dòng chung: bảng cân đối dài dễ vượt 40 dòng, cắt ngắn sẽ làm dòng
    # chi tiết áp chót trông như dòng tổng cuối (nhóm BWE).
    table_scan = nodes[start:min(len(nodes), start + 240)]
    for n in table_scan:
        if not started:
            if is_noise(n):
                continue
            if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
                if n.line_no - anchor.line_no > 6:
                    break
                started = True
                table_rows.append(n)
                continue
            # Không cho phép văn xuôi tùy ý trước bảng tách rời.
            break
        else:
            if n.pattern_id == "SP_MARKDOWN_TABLE_ROW":
                table_rows.append(n)
                continue
            break

    if table_rows:
        for n in reversed(table_rows):
            if len(n.periods) >= 2 and len(n.values) >= 2:
                return (
                    list(zip(n.periods[:2], n.values[:2])),
                    [],
                    n.unit or n.inherited_unit,
                    "detached_total_terminal_table_row",
                )

    return None


def collect_observation(
    anchor: StructuralNode,
    nodes: list[StructuralNode],
    selected,
    candidates,
    guide: UniversalGuide,
    *,
    semantic_anchor_indices: set[int] | None = None,
):
    """Thu thập payload giá trị gắn với một anchor semantic.

    Bộ thu dừng ở anchor child semantic kế tiếp. Ranh giới này ngăn dòng parent
    nhận các giá trị thuộc child lồng nhau hoặc dòng nguồn kế tiếp.
    """
    semantic_anchor_indices = semantic_anchor_indices or set()

    values = []
    period_values = []
    note = anchor.note
    code = anchor.code
    unit = anchor.unit or anchor.inherited_unit
    evidence = [f"anchor_pattern:{anchor.pattern_id}"]

    # Cấu trúc tự chứa.
    if anchor.pattern_id == "SP_MARKDOWN_TABLE_ROW":
        if anchor.periods and len(anchor.periods) == len(anchor.values):
            period_values = list(zip(anchor.periods, anchor.values))
        else:
            values = list(anchor.values)
        evidence.append("table_self_contained")

    elif anchor.pattern_id == "SP_PIPE_DELIMITED_INLINE_ROW":
        values, period_values, pipe_code, pipe_note = _parse_pipe_inline(anchor, guide)
        code = code or pipe_code
        note = note or pipe_note
        evidence.append("pipe_self_contained")

    elif anchor.pattern_id == "SP_MULTI_PERIOD_INLINE":
        if len(anchor.periods) >= 2 and len(anchor.values) >= 2:
            period_values = _period_value_pairs(anchor.periods, anchor.values)
        evidence.append("multi_period_inline")

    elif anchor.pattern_id == "SP_CODE_NOTE_PERIOD_INLINE_ROW":
        # document.py đã bỏ metadata mã/thuyết minh khỏi giá trị.
        # Resolver gán payload đầu/thứ hai theo context hiện tại/trước đây.
        values = list(anchor.values)
        code = code or anchor.code
        note = note or anchor.note
        evidence.append("code_note_period_inline_self_contained")

    elif anchor.pattern_id == "SP_LABEL_VALUE_INLINE":
        values = list(anchor.values)
        if anchor.inherited_period and values:
            period_values = [(anchor.inherited_period, v) for v in values]
            values = []
        evidence.append("inline_value")

    # Ưu tiên child tổng trực tiếp rõ ràng hơn chi tiết sâu hơn.
    local_summary_found = False
    for child_idx in anchor.children:
        child = nodes[child_idx]
        if (
            child.pattern_id == "SP_LABEL_VALUE_INLINE"
            and child.lhs
            and fold(child.lhs) in {"tong", "tong cong", "total", "tong so"}
            and child.values
        ):
            local_summary_found = True
            if anchor.inherited_period:
                for v in child.values:
                    period_values.append((anchor.inherited_period, v))
            else:
                values.extend(child.values)
            unit = unit or child.unit or child.inherited_unit
    if local_summary_found:
        evidence.append("direct_generic_summary_child")

    # Với cấu trúc container/child, chỉ duyệt trong record semantic này.
    bounded = _bounded_descendants(
        anchor,
        nodes,
        semantic_anchor_indices=semantic_anchor_indices - {anchor.node_index},
        max_depth=6,
    )

    for d in bounded:
        if local_summary_found and d.pattern_id != "SP_NAMED_ATTRIBUTE":
            continue
        if d.pattern_id == "SP_NAMED_ATTRIBUTE" and d.lhs:
            key = fold(d.lhs)
            if key in NOTE_KEYS:
                if selected.kind != "section":
                    note = note or (d.rhs.strip() if d.rhs else None)
            elif key in CODE_KEYS:
                code = code or (d.rhs.strip() if d.rhs else None)
            elif key == "so tien" and d.values:
                values.extend(d.values)
            continue

        if d.pattern_id == "SP_PERIOD_VALUE_ATTRIBUTE":
            p = whole_text_period(d.lhs or "", d.line_no, guide)
            if p and d.values:
                period_values.append((p, d.values[0]))
            continue

        if d.pattern_id == "SP_PERIOD_CONTAINER":
            continue

        # Child tổng chung lặp lại là các cột kỳ theo vị trí:
        #   TỔNG TÀI SẢN
        #       Tổng: current
        #       Tổng: previous
        # Dạng này thường gặp khi LLM bỏ nhãn ngày nhưng giữ thứ tự dòng từ header.
        if (
            d.parent_index == anchor.node_index
            and d.pattern_id == "SP_LABEL_VALUE_INLINE"
            and d.lhs
            and fold(d.lhs) in {"tong", "tong cong", "total", "tong so"}
            and d.values
        ):
            values.extend(d.values)
            unit = unit or d.unit or d.inherited_unit
            continue

        # Payload kỳ ở child trực tiếp dạng chung. Một số serializer OCR/LLM bọc
        # tổng như sau:
        #   TỔNG NGUỒN VỐN
        #       Tổng cộng: value (2025); value (2024)
        # Child không phải anchor semantic canonical nhưng vẫn mang giá trị kỳ
        # của record parent.
        if (
            d.parent_index == anchor.node_index
            and d.periods
            and d.values
            and len(d.periods) == len(d.values)
        ):
            period_values.extend(zip(d.periods, d.values))
            unit = unit or d.unit or d.inherited_unit
            continue

        # Payload số ở child trực tiếp dạng chung. Bao quát giá trị serialize
        # thành bullet kèm annotation đơn vị như "12.410... (Không rõ đơn vị)".
        # Anchor child semantic đã bị loại trong lượt duyệt giới hạn.
        if (
            d.parent_index == anchor.node_index
            and d.values
            and not d.lhs
            and not d.periods
            and d.pattern_id in {"SP_LABEL_CONTAINER", "SP_VALUE_ONLY_POSITIONAL"}
        ):
            values.extend(d.values)
            unit = unit or d.unit or d.inherited_unit
            continue

        # Child trực tiếp dưới kỳ kế thừa, nhưng chỉ khi không phải anchor semantic.
        if d.pattern_id == "SP_LABEL_VALUE_INLINE" and d.inherited_period and d.values:
            if d.parent_index == anchor.node_index:
                for v in d.values:
                    period_values.append((d.inherited_period, v))
            continue

        # Serialize A1/BAB: child có khóa lặp lại là cột theo vị trí.
        # Ví dụ:
        #   Tiền gửi tại NHNN
        #       5.2: 1.219.788
        #       5.2: 798.225
        # Ở đây 5.2 là khóa thuyết minh/tham chiếu, còn hai giá trị tương ứng với
        # context cột hiện tại/trước đây.
        if (
            d.pattern_id == "SP_LABEL_VALUE_INLINE"
            and d.parent_index == anchor.node_index
            and d.values
            and d.lhs
            and re.fullmatch(r"\d+(?:\.\d+)+", d.lhs.strip())
        ):
            note = note or d.lhs.strip()
            values.extend(d.values)
            continue

        if d.pattern_id == "SP_VALUE_ONLY_POSITIONAL" and d.values:
            values.extend(d.values)

        if unit is None and (d.unit or d.inherited_unit):
            unit = d.unit or d.inherited_unit

    # Fallback tuần tự cho nhãn plain/không phải parent có thuộc tính serialize
    # thành bullet ngay sau đó.
    if not period_values and not values:
        seq_periods, seq_note, seq_code, seq_unit, seq_values = _sequential_local_attributes(
            anchor,
            nodes,
            semantic_anchor_indices - {anchor.node_index},
            guide,
        )
        if seq_periods or seq_values:
            period_values.extend(seq_periods)
            values.extend(seq_values)
            if selected.kind != "section":
                note = note or seq_note
            code = code or seq_code
            unit = unit or seq_unit
            evidence.append("sequential_local_attribute_fallback")

    # Tổng tài chính rõ có thể bị tách payload khỏi nhãn semantic. Chạy sau bộ
    # thu thường để đây chỉ là khôi phục có mục tiêu ở cấp tổng. Payload khôi
    # phục ghi đè artifact công thức/mã vô tình bị tokenize từ chính nhãn tổng.
    detached = _recover_detached_total_payload(anchor, nodes, selected)
    if detached and not period_values:
        detached_period_values, detached_values, detached_unit, detached_evidence = detached
        if detached_period_values or detached_values:
            period_values = detached_period_values
            values = detached_values
            unit = unit or detached_unit
            evidence.append(detached_evidence)

    if period_values:
        values = []

    return FieldObservation(
        anchor_node_index=anchor.node_index,
        line_no=anchor.line_no,
        source_label=anchor.label_text or anchor.text,
        selected=selected,
        all_candidates=candidates,
        pattern_id=anchor.pattern_id,
        pattern_name=anchor.pattern_name,
        values=values,
        period_values=period_values,
        note=note,
        code=code,
        unit=unit,
        evidence=evidence + [
            f"semantic_boundaries={len(semantic_anchor_indices)}",
            f"bounded_descendants={len(bounded)}",
        ],
    )
