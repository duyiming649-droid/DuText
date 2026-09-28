from __future__ import annotations

import httpx

from dutext.jsonutil import parse_json_object
from dutext.models import GenerateRequest, Intent, RectBox
from dutext.pdf_text import numbered_lines, page_words
from dutext.pipeline import intents_from_compose_strokes
from dutext.secrets import get_api_key

VISION_MODEL = "deepseek-v4-flash-vision-exp"
PRO_MODEL = "deepseek-v4-pro"
BASE_URL = "https://api.deepseek.com"
REPAIR_TRIES = 2


class LLMError(RuntimeError):
    pass


def _chat(model: str, messages: list, *, json_mode: bool = True) -> str:
    key = get_api_key()
    if not key:
        raise LLMError("还没有 API Key。请在顶栏粘贴 DeepSeek 密钥并保存。")
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120.0,
        )
    except httpx.TimeoutException as exc:
        raise LLMError("DeepSeek 请求超时。") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"无法连接 DeepSeek：{exc}") from exc

    if response.status_code == 401:
        raise LLMError("API Key 无效，请重新粘贴保存。")
    if response.status_code == 429:
        raise LLMError("DeepSeek 限流了，稍后再试。")
    if response.status_code >= 400:
        detail = response.text[:400]
        raise LLMError(f"DeepSeek 接口出错（{response.status_code}）：{detail}")

    data = response.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not str(content).strip():
        raise LLMError("模型返回了空内容。")
    return str(content)


def perceive(page: int, image_jpeg_b64: str, pdf_file: str) -> list[Intent]:
    """Vision Exp reads the annotated page. One entry per ink color/instruction."""
    page_text = numbered_lines(pdf_file, page)
    prompt = (
        "You see a screenshot of one PDF page. Colored ink is the user's overlay. "
        "Red, yellow, and blue marks are SEPARATE instructions, in that order. "
        "There are at most three instructions.\n"
        "Each instruction currently means: an ellipse/circle around body text "
        "plus an exclamation mark beside that circle → make that text bold.\n"
        "The page text layer below is numbered per line, like [L07]. Copy each "
        "\"text\" value CHARACTER-FOR-CHARACTER from those numbered lines. Never "
        "paraphrase, never fix grammar, never add or drop words.\n"
        "Return JSON only:\n"
        "{\n"
        '  "summary": "one short Chinese sentence covering all instructions",\n'
        '  "instructions": [\n'
        '    {"color": "red"|"yellow"|"blue", "kind": "emphasize"|"none", '
        '"text": "exact words to bold", "summary": "short Chinese"}\n'
        "  ]\n"
        "}\n"
        'Example: {"summary": "将红圈句子加粗", "instructions": [{"color": "red", '
        '"kind": "emphasize", "text": "spatial marks are a better control language '
        'than prompts", "summary": "红圈句子加粗"}]}\n'
        "Omit a color if it was not used. If nothing is recognizable, instructions must be empty.\n"
        f"Page number: {page}\n"
        f"Numbered page text layer:\n{page_text}"
    )
    content = _chat(
        VISION_MODEL,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_jpeg_b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    )
    data = parse_json_object(content)
    color_group = {"red": 0, "yellow": 1, "blue": 2}
    intents: list[Intent] = []
    for item in data.get("instructions") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "none")
        text = str(item.get("text") or "").strip()
        if kind != "emphasize" or not text:
            continue
        color = str(item.get("color") or "").lower()
        intents.append(
            Intent(
                kind="emphasize",
                page=page,
                text=text,
                summary=str(item.get("summary") or "").strip(),
                color=color,
                group=color_group.get(color, len(intents)),
            )
        )
    if not intents:
        raise LLMError(
            str(data.get("summary") or "").strip() or "没有识别到「圈选 + 感叹号」。"
        )
    if not (intents[0].summary or "").strip():
        intents[0].summary = str(data.get("summary") or "").strip()
    return intents[:3]


def edit_tex(tex: str, intents: list[Intent] | Intent) -> str:
    """V4 Pro edits source. Markup only; do not rewrite the prose."""
    if isinstance(intents, Intent):
        intents = [intents]
    spans = "\n".join(f"{i + 1}. {item.text}" for i, item in enumerate(intents))
    prompt = (
        "You edit LaTeX. Do not change the wording of the document. Do not reflow, "
        "rewrap or reformat any line you are not asked to change. "
        "Task: wrap EACH listed span in \\textbf{...} at its first remaining "
        "source occurrence. Skip a span if it is already bold.\n"
        'Return JSON: {"tex": "<full file>", "note": "short Chinese"}.\n'
        f"Spans to emphasize:\n{spans}\n\n"
        f"Current source:\n{tex}"
    )
    data = parse_json_object(_chat(PRO_MODEL, [{"role": "user", "content": prompt}]))
    new_tex = str(data.get("tex") or "").strip()
    if not new_tex:
        raise LLMError("Pro 没有返回 TeX。")
    return new_tex


def repair_tex(tex: str, log: str) -> str:
    prompt = (
        "The LaTeX below failed to compile. Fix only what is needed so it "
        "compiles. Do not rewrite the paper.\n"
        'Return JSON: {"tex": "<full file>"}.\n\n'
        f"Log tail:\n{log[-4000:]}\n\n"
        f"Source:\n{tex}"
    )
    data = parse_json_object(_chat(PRO_MODEL, [{"role": "user", "content": prompt}]))
    new_tex = str(data.get("tex") or "").strip()
    if not new_tex:
        raise LLMError("编译修复没有返回 TeX。")
    return new_tex


def _notes_block(request: GenerateRequest) -> str:
    labels = {
        0: "instruction 1 / red",
        1: "instruction 2 / yellow",
        2: "instruction 3 / blue",
        3: "instruction 4 / black template pen",
    }
    lines: list[str] = []
    for item in request.notes:
        text = (item.note or "").strip()
        if not text:
            continue
        lines.append(f"- {labels.get(item.group, f'group {item.group}')}: {text}")
    return "\n".join(lines) if lines else "(none)"


def _rect_json(rect: RectBox | None) -> dict | None:
    if rect is None:
        return None
    box = rect.normalized()
    return {"x": round(box.x, 1), "y": round(box.y, 1), "w": round(box.w, 1), "h": round(box.h, 1)}


def _merge_compose_intents(base: list[Intent], vision: list[Intent]) -> list[Intent]:
    by_group = {item.group: item for item in base}
    for item in vision:
        current = by_group.get(item.group)
        if current is None:
            by_group[item.group] = item
            continue
        if item.text and not current.text:
            current.text = item.text
        if item.dest_rect is not None and current.dest_rect is None:
            current.dest_rect = item.dest_rect
        if item.source_rect is not None and current.source_rect is None:
            current.source_rect = item.source_rect
        if item.summary:
            current.summary = item.summary
        if item.note and not current.note:
            current.note = item.note
    return [by_group[key] for key in sorted(by_group)]


def _vision_compose(request: GenerateRequest, pdf_file: str) -> list[Intent]:
    page_text = numbered_lines(pdf_file, request.page)
    parsed = intents_from_compose_strokes(request, pdf_file)
    geometry = []
    for item in parsed:
        geometry.append(
            {
                "group": item.group,
                "kind": item.kind,
                "color": item.color,
                "text_from_pdf": item.text,
                "source_rect": _rect_json(item.source_rect),
                "dest_rect": _rect_json(item.dest_rect),
                "note": item.note,
            }
        )
    prompt = (
        "You see ONE screenshot: LEFT is the original PDF page, RIGHT is a blank canvas. "
        "Colored marks and black ink are the user's overlay. Coordinates in the geometry "
        "block are PDF points, origin top-left of each page.\n"
        "There are at most three COLOR instructions (red, yellow, blue in that order) PLUS "
        "an optional BLACK template pen (instruction 4). Black ink is NOT one object — "
        "respect where each stroke was drawn and what it depicts. Clean it up only: "
        "straighten wobbly lines, even out spacing. Do not invent extra decorations.\n"
        "A typical color instruction: a rectangle around source text on the LEFT, an arrow "
        "to the RIGHT, and a same-color destination rectangle. Put that text into the dest "
        "box. Fit by font size and leading. If the original size already fits, keep it. "
        "Copy \"text\" CHARACTER-FOR-CHARACTER from the numbered text layer below — never paraphrase.\n"
        "User notes below are extra constraints for THAT instruction only (font, leading, ...).\n"
        "Return JSON only:\n"
        "{\n"
        '  "summary": "short Chinese covering all instructions",\n'
        '  "instructions": [\n'
        '    {"group": 0, "color": "red"|"yellow"|"blue"|"black", '
        '"kind": "place"|"template"|"none", "text": "exact source wording", '
        '"summary": "short Chinese", '
        '"dest_rect": {"x":0,"y":0,"w":0,"h":0} or null}\n'
        "  ]\n"
        "}\n"
        f"Page number: {request.page}\n"
        f"Page size: {request.page_width} x {request.page_height} pt\n"
        f"User notes:\n{_notes_block(request)}\n"
        f"Geometry from overlay:\n{geometry}\n"
        f"Numbered page text layer:\n{page_text}"
    )
    content = _chat(
        VISION_MODEL,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{request.image_jpeg_base64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    )
    data = parse_json_object(content)
    color_group = {"red": 0, "yellow": 1, "blue": 2, "black": 3}
    intents: list[Intent] = []
    for item in data.get("instructions") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "none")
        if kind not in {"place", "template"}:
            continue
        color = str(item.get("color") or "").lower()
        group = item.get("group")
        if group is None:
            group = color_group.get(color, 0)
        dest = None
        raw_dest = item.get("dest_rect")
        if isinstance(raw_dest, dict):
            dest = RectBox(
                x=float(raw_dest.get("x") or 0),
                y=float(raw_dest.get("y") or 0),
                w=float(raw_dest.get("w") or 0),
                h=float(raw_dest.get("h") or 0),
            )
        intents.append(
            Intent(
                kind=kind,  # type: ignore[arg-type]
                page=request.page,
                text=str(item.get("text") or "").strip(),
                dest_rect=dest,
                summary=str(item.get("summary") or "").strip(),
                color=color,
                group=int(group),
                note="",
            )
        )
    if intents and not (intents[0].summary or "").strip():
        intents[0].summary = str(data.get("summary") or "").strip()
    return intents


def perceive_compose(request: GenerateRequest, pdf_file: str) -> list[Intent]:
    """Compose mode: place-in-box plus optional black template marks."""
    base = intents_from_compose_strokes(request, pdf_file)
    if request.image_jpeg_base64.strip():
        try:
            vision = _vision_compose(request, pdf_file)
            base = _merge_compose_intents(base, vision)
        except LLMError:
            if not base:
                raise
    if not base:
        raise LLMError("没有识别到画版指令。请用矩形圈出左边文字，箭头指向右边同色目标框；黑笔可选。")
    notes = {item.group: item.note.strip() for item in request.notes if item.note.strip()}
    for intent in base:
        if intent.group in notes:
            intent.note = notes[intent.group]
    return base


def edit_tex_compose(tex: str, intents: list[Intent], request: GenerateRequest) -> str:
    """V4 Pro rewrites the visible page from compose marks. Single-page only."""
    places = [item for item in intents if item.kind == "place"]
    templates = [item for item in intents if item.kind == "template"]
    spec_lines: list[str] = []
    for item in places:
        spec_lines.append(
            f"- PLACE group {item.group} color={item.color or '-'}\n"
            f"  source text: {item.text or '(empty)'}\n"
            f"  dest_rect (top-left PDF pt, RIGHT canvas): {_rect_json(item.dest_rect)}\n"
            f"  extra note: {item.note or '(none)'}"
        )
    if templates:
        spec_lines.append(
            "- TEMPLATE (black pen, instruction 4): recreate each mark where it was drawn. "
            "Do not merge all black ink into one decoration. Straighten near-straight strokes, "
            "even out spacing. Extra note: "
            + (templates[0].note or "(none)")
        )
    black_pts = []
    for stroke in request.strokes:
        if stroke.tool != "black" and stroke.group != 3:
            continue
        if stroke.points:
            sample = [{"x": round(p.x, 1), "y": round(p.y, 1)} for p in stroke.points[:: max(1, len(stroke.points) // 12)]]
            black_pts.append({"side": stroke.side, "points": sample})
        elif stroke.rect:
            black_pts.append({"side": stroke.side, "rect": _rect_json(stroke.rect)})
    if black_pts:
        spec_lines.append(f"- black stroke samples: {black_pts}")

    prompt = (
        "You edit LaTeX for DuText compose mode. This is a SINGLE-PAGE free layout. "
        "Do not rewrite the wording of passages; move and typeset them.\n"
        "Screenshot (left original, right blank canvas) plus the spec below is the user intent.\n"
        "RULES (all mandatory):\n"
        "R1. PLACE: put that exact text into dest_rect on the output page. Fit inside the box "
        "by adjusting font size and baselineskip/leading. If the original size already fits the "
        "box, KEEP the original size. Prefer minipage/parbox/tikz nodes. Coordinates are "
        "PDF points, origin top-left; convert to TeX (origin bottom-left) as needed. "
        "Page size in pt is given below.\n"
        "R2. TEMPLATE: black pen is the layout template (rules, frames). Honour each mark's "
        "location and shape; only clean it up — straighten near-straight strokes, even out "
        "spacing, never merge all black ink into one decoration. Optional — skip if none.\n"
        "R3. WORDING: every passage keeps its exact source wording. You may change only "
        "layout, fonts and spacing.\n"
        "R4. Output is exactly ONE page. Other pages of a multi-page source are out of scope.\n"
        "R5. If there are NO place boxes, keep the original document body and only add the "
        "cleaned template graphics (e.g. a bottom rule).\n"
        "R6. Packages you may use: geometry, tikz, eso-pic, graphicx, setspace. Avoid exotic fonts.\n"
        "Each user note applies only to its instruction, together with this system brief.\n"
        "Before returning, verify R1-R6 yourself and report honestly in \"checks\".\n"
        'Return JSON: {"tex": "<full file>", "note": "short Chinese", '
        '"checks": {"wording_unchanged": true, "one_page": true, "in_dest_boxes": true}}.\n'
        f"Page size: {request.page_width} x {request.page_height} pt\n"
        f"User notes:\n{_notes_block(request)}\n"
        f"Spec:\n{chr(10).join(spec_lines) or '(empty)'}\n\n"
        f"Current source:\n{tex}"
    )
    data = parse_json_object(_chat(PRO_MODEL, [{"role": "user", "content": prompt}]))
    checks = data.get("checks")
    if isinstance(checks, dict):
        failed = sorted(name for name, ok in checks.items() if ok is False)
        if failed:
            raise LLMError("Pro 自检未通过（" + ", ".join(failed) + "），改用确定性排版。")
    new_tex = str(data.get("tex") or "").strip()
    if not new_tex:
        raise LLMError("Pro 没有返回 TeX。")
    return new_tex
