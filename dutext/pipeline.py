from __future__ import annotations

from dutext.apply_bold import ApplyError, apply_bold
from dutext.gestures import has_exclamation, pick_ellipse
from dutext.models import GenerateRequest, Intent, RectBox, Stroke
from dutext.pdf_text import (
    join_words,
    page_words,
    words_inside_ellipse,
    words_inside_rect,
)


class GestureError(ValueError):
    pass


def recognize(request: GenerateRequest, pdf_file: str) -> Intent:
    """Map overlay strokes to a single intent. Swap this out for a vision model later."""
    picked = pick_ellipse(request.strokes)
    if picked is None:
        raise GestureError("No circle found. Draw an ellipse around the words, then a ! beside it.")
    ellipse, skip = picked
    if not has_exclamation(request.strokes, ellipse, skip):
        raise GestureError("Found a circle, but no exclamation mark beside it.")
    words = words_inside_ellipse(page_words(pdf_file, request.page), ellipse)
    text = join_words(words)
    if not text.strip():
        raise GestureError("The circle does not contain any text on this page.")
    return Intent(kind="emphasize", page=request.page, text=text, ellipse=ellipse)


def apply_intent(tex: str, intent: Intent) -> str:
    if intent.kind == "emphasize":
        try:
            new_tex, used = apply_bold(tex, intent.text)
            intent.text = used
            return new_tex
        except ApplyError as exc:
            raise GestureError(str(exc)) from exc
    raise GestureError(f"unsupported intent {intent.kind}")


def apply_intents(tex: str, intents: list[Intent]) -> str:
    for intent in intents:
        tex = apply_intent(tex, intent)
    return tex


def _ellipse_as_rect(ellipse) -> RectBox:
    return RectBox(
        x=ellipse.cx - ellipse.rx,
        y=ellipse.cy - ellipse.ry,
        w=2 * ellipse.rx,
        h=2 * ellipse.ry,
    )


def _is_black(stroke: Stroke) -> bool:
    return stroke.tool == "black" or stroke.group == 3


def _notes_map(request: GenerateRequest) -> dict[int, str]:
    return {item.group: item.note.strip() for item in request.notes if item.note.strip()}


def intents_from_compose_strokes(request: GenerateRequest, pdf_file: str) -> list[Intent]:
    """Turn rect + arrow + dest-rect (and optional black template) into intents."""
    words = page_words(pdf_file, request.page)
    notes = _notes_map(request)
    buckets: dict[int, dict] = {i: {"left": [], "right": [], "color": ""} for i in range(3)}
    black_strokes: list[Stroke] = []

    for stroke in request.strokes:
        if _is_black(stroke):
            black_strokes.append(stroke)
            continue
        group = max(0, min(int(stroke.group), 2))
        bucket = buckets[group]
        if stroke.color:
            bucket["color"] = stroke.color
        rect = stroke.rect.normalized() if stroke.rect else None
        if stroke.tool == "ellipse" and stroke.ellipse:
            rect = _ellipse_as_rect(stroke.ellipse)
        if rect is not None:
            side = stroke.side or "left"
            bucket[side].append(rect)

    intents: list[Intent] = []
    for group in range(3):
        bucket = buckets[group]
        if not bucket["left"] and not bucket["right"]:
            continue
        texts = [join_words(words_inside_rect(words, rect)) for rect in bucket["left"]]
        text = " ".join(part for part in texts if part).strip()
        source = bucket["left"][0] if bucket["left"] else None
        dest = bucket["right"][0] if bucket["right"] else None
        snippet = text[:48] + ("…" if len(text) > 48 else "")
        intents.append(
            Intent(
                kind="place",
                page=request.page,
                text=text,
                source_rect=source,
                dest_rect=dest,
                group=group,
                color=bucket["color"],
                note=notes.get(group, ""),
                summary=f"将选中文字排进右边目标框" + (f"：{snippet}" if snippet else ""),
            )
        )

    if black_strokes:
        intents.append(
            Intent(
                kind="template",
                page=request.page,
                text="",
                group=3,
                color="#111111",
                note=notes.get(3, ""),
                summary="按黑笔位置绘制版面元素：画在哪就放在哪，拉直并均匀，不把全部黑笔当成一块。",
            )
        )
    return intents


def _tex_escape(text: str) -> str:
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(ch, ch) for ch in text)


def _straighten_segment(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    if abs(y1 - y0) < 10 and abs(x1 - x0) >= abs(y1 - y0):
        y = (y0 + y1) / 2
        return x0, y, x1, y
    if abs(x1 - x0) < 10 and abs(y1 - y0) >= abs(x1 - x0):
        x = (x0 + x1) / 2
        return x, y0, x, y1
    return x0, y0, x1, y1


def _black_draw_commands(request: GenerateRequest) -> str:
    lines: list[str] = []
    for stroke in request.strokes:
        if not _is_black(stroke):
            continue
        side = stroke.side or "left"
        if stroke.rect and side == "right":
            box = stroke.rect.normalized()
            x0, y0 = box.x, box.y
            x1, y1 = box.x + box.w, box.y + box.h
            lines.append(
                rf"  \draw[line width=0.7pt] ({x0:.1f}pt,{-y0:.1f}pt) rectangle ({x1:.1f}pt,{-y1:.1f}pt);"
            )
            continue
        if stroke.tool in {"black", "pen"} and len(stroke.points) >= 2:
            pts = stroke.points
            # Draw as consecutive straightened segments so a bottom rule stays a rule.
            for i in range(len(pts) - 1):
                x0, y0, x1, y1 = _straighten_segment(pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y)
                if abs(x1 - x0) < 0.4 and abs(y1 - y0) < 0.4:
                    continue
                lines.append(
                    rf"  \draw[line width=0.8pt] ({x0:.1f}pt,{-y0:.1f}pt) -- ({x1:.1f}pt,{-y1:.1f}pt);"
                )
    return "\n".join(lines)


def _inject_template_overlay(tex: str, request: GenerateRequest) -> str:
    draws = _black_draw_commands(request)
    if not draws:
        return tex
    overlay = (
        "\\usepackage{eso-pic}\n"
        "\\usepackage{tikz}\n"
        "\\AddToShipoutPictureFG*{\n"
        "  \\AtPageUpperLeft{%\n"
        "    \\begin{tikzpicture}[overlay, x=1pt, y=1pt]\n"
        f"{draws}\n"
        "    \\end{tikzpicture}%\n"
        "  }\n"
        "}\n"
    )
    if "\\begin{document}" not in tex:
        return overlay + tex
    if "eso-pic" not in tex:
        tex = tex.replace("\\begin{document}", overlay + "\\begin{document}", 1)
    return tex


def _rebuild_compose_page(intents: list[Intent], request: GenerateRequest) -> str:
    width = request.page_width
    height = request.page_height
    nodes: list[str] = []
    for intent in intents:
        if intent.kind != "place" or not intent.text:
            continue
        if intent.dest_rect is None:
            continue
        box = intent.dest_rect.normalized()
        note = f" % {intent.note}" if intent.note else ""
        body = _tex_escape(intent.text)
        nodes.append(
            rf"  \node[anchor=north west, inner sep=2pt, text width={box.w:.1f}pt] "
            rf"at ({box.x:.1f}pt,{-box.y:.1f}pt) "
            rf"{{\parbox[t][{box.h:.1f}pt][t]{{{box.w:.1f}pt}}{{\raggedright {body}}}}};{note}"
        )
    draws = _black_draw_commands(request)
    return (
        f"\\documentclass{{article}}\n"
        f"\\usepackage[paperwidth={width:.1f}pt,paperheight={height:.1f}pt,margin=0pt]{{geometry}}\n"
        "\\usepackage{tikz}\n"
        "\\pagestyle{empty}\n"
        "\\begin{document}\n"
        "\\noindent\\begin{tikzpicture}[x=1pt, y=1pt, overlay, remember picture]\n"
        "  \\fill[white] (0,0) rectangle "
        f"({width:.1f}pt,{-height:.1f}pt);\n"
        + "\n".join(nodes)
        + ("\n" + draws if draws else "")
        + "\n\\end{tikzpicture}\n\\end{document}\n"
    )


def apply_compose(tex: str, intents: list[Intent], request: GenerateRequest) -> str:
    """Deterministic fallback when Pro cannot rewrite the page."""
    places = [item for item in intents if item.kind == "place" and item.text and item.dest_rect]
    if not places:
        return _inject_template_overlay(tex, request)
    return _rebuild_compose_page(intents, request)
