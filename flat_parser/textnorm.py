from __future__ import annotations

import html
import re
import unicodedata

from .models import SourceLine


PAGE_RE = re.compile(r"^\s*#\s*Page\s+(\d+)\s*$", re.I)
HEADING_RE = re.compile(r"^\s*(#{1,6})\s+")
BULLET_RE = re.compile(r"^(\s*)(\\?\*|-|\+|•)\s+")
NUMBERING_RE = re.compile(
    r"^\s*(?:"
    r"\(?\d+(?:\.\d+)*\)?[.)-]?"
    r"|[IVXLC]+[.)]"
    r"|[A-Za-z][.)]"
    r")\s+",
    re.I,
)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


def strip_inline_markdown(text: str) -> str:
    text = text.replace(r"\*", "*").replace(r"\_", "_")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def strip_numbering(text: str) -> str:
    out = text.strip()
    for _ in range(3):
        new = NUMBERING_RE.sub("", out).strip()
        if new == out:
            return out
        out = new
    return out


def normalize_lines(raw_text: str) -> list[SourceLine]:
    result = []
    current_page = None

    for line_no, raw in enumerate(raw_text.splitlines(), start=1):
        raw = html.unescape(unicodedata.normalize("NFKC", raw).replace("\u00a0", " "))
        page_m = PAGE_RE.match(raw)
        if page_m:
            current_page = int(page_m.group(1))

        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))

        heading_m = HEADING_RE.match(raw)
        heading_level = len(heading_m.group(1)) if heading_m else 0

        bullet_m = BULLET_RE.match(raw)
        is_bullet = bool(bullet_m)
        bullet_marker = bullet_m.group(2).replace("\\", "") if bullet_m else None

        clean = strip_inline_markdown(raw)
        clean = HEADING_RE.sub("", clean)
        clean = BULLET_RE.sub("", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        depth = max(0, indent // 4)
        if is_bullet:
            depth += 1

        result.append(
            SourceLine(
                line_no=line_no,
                raw=raw,
                clean=clean,
                indent=indent,
                bullet_depth=depth,
                is_bullet=is_bullet,
                bullet_marker=bullet_marker,
                heading_level=heading_level,
                has_pipe="|" in clean,
                is_blank=(clean == ""),
                page_no=current_page,
            )
        )
    return result


TRAILING_FINANCIAL_META_RE = re.compile(
    r"\s*\((?:"
    r"(?:ma\s*so|mã\s*số)\s*[:=]?\s*[^)]*"
    r"|(?:thuyet\s*minh|thuyết\s*minh|tm)\s*[:=]?\s*[\d.]+"
    r"|\d{2,3}"
    r"|\d{2,3}(?:\.\d+)?\s*(?:=|\+|-)\s*[^)]*"
    r")\)\s*$",
    re.I,
)


def strip_inline_financial_metadata(text: str) -> str:
    """
    Remove display-only metadata appended to a financial label, e.g.
      NỢ PHẢI TRẢ (Mã số: 300)
      TỔNG CỘNG TÀI SẢN (270=100+200)
      TỔNG CỘNG NGUỒN VỐN (440 = 300 + 400)

    This is semantic-label cleanup only; raw text and numeric provenance remain
    untouched in the source node.
    """
    out = (text or "").strip()
    for _ in range(2):
        new = TRAILING_FINANCIAL_META_RE.sub("", out).strip()
        if new == out:
            break
        out = new
    return out


FINANCIAL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"[A-Z]\s*[-–—.:)]\s*"
    r"|[IVXLC]+\s*[-–—.:)]\s*"
    r"|\d+(?:\.\d+)*\s*[-–—.:)]\s*"
    r")",
    re.I,
)


def strip_financial_prefix(text: str) -> str:
    """
    Remove display-only section prefixes such as:
      A - TÀI SẢN NGẮN HẠN
      C - NỢ PHẢI TRẢ
      I. Tiền mặt...
    Raw source text remains unchanged elsewhere.
    """
    out = text.strip()
    for _ in range(2):
        new = FINANCIAL_PREFIX_RE.sub("", out).strip()
        if new == out:
            break
        out = new
    return out
