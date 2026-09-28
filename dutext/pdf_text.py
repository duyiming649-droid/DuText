from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from dutext.models import Ellipse, RectBox


@dataclass(frozen=True)
class WordBox:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int
    word: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def page_words(pdf_file: str, page_number: int) -> list[WordBox]:
    """page_number is 1-based. Coordinates: origin top-left, PDF points."""
    doc = pymupdf.open(pdf_file)
    try:
        index = page_number - 1
        if index < 0 or index >= doc.page_count:
            raise ValueError(f"page {page_number} out of range")
        page = doc[index]
        words: list[WordBox] = []
        for item in page.get_text("words"):
            x0, y0, x1, y1, text, block, line, word = item[:8]
            if not str(text).strip():
                continue
            words.append(
                WordBox(
                    float(x0),
                    float(y0),
                    float(x1),
                    float(y1),
                    str(text),
                    int(block),
                    int(line),
                    int(word),
                )
            )
        return words
    finally:
        doc.close()


def words_inside_ellipse(words: list[WordBox], ellipse: Ellipse) -> list[WordBox]:
    inside = [w for w in words if ellipse.contains(w.cx, w.cy)]
    inside.sort(key=lambda w: (w.block, w.line, w.word))
    return inside


def join_words(words: list[WordBox]) -> str:
    return " ".join(w.text for w in words)


def numbered_lines(pdf_file: str, page_number: int) -> str:
    """Page text as [Lnn]-prefixed lines in reading order.

    Prompts use this so the model can quote a line verbatim (or cite its
    number) instead of paraphrasing; the tags also make omissions visible.
    """
    lines: dict[tuple[int, int], list[WordBox]] = {}
    for word in page_words(pdf_file, page_number):
        lines.setdefault((word.block, word.line), []).append(word)
    out: list[str] = []
    for index, key in enumerate(sorted(lines), start=1):
        row = sorted(lines[key], key=lambda w: w.word)
        out.append(f"[L{index:02d}] " + " ".join(w.text for w in row))
    return "\n".join(out)


def words_inside_rect(words: list[WordBox], rect: RectBox) -> list[WordBox]:
    box = rect.normalized()
    x0, y0 = box.x, box.y
    x1, y1 = box.x + box.w, box.y + box.h
    inside = [w for w in words if x0 <= w.cx <= x1 and y0 <= w.cy <= y1]
    inside.sort(key=lambda w: (w.block, w.line, w.word))
    return inside
