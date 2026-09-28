from __future__ import annotations

import math

from dutext.models import Ellipse, Point, Stroke


def _bbox(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def ellipse_from_bbox(x0: float, y0: float, x1: float, y1: float) -> Ellipse:
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    rx = abs(x1 - x0) / 2
    ry = abs(y1 - y0) / 2
    return Ellipse(cx=cx, cy=cy, rx=max(rx, 1.0), ry=max(ry, 1.0))


def stroke_ellipse(stroke: Stroke) -> Ellipse | None:
    if stroke.tool == "ellipse" and stroke.ellipse is not None:
        return stroke.ellipse
    if len(stroke.points) < 8:
        return None
    x0, y0, x1, y1 = _bbox(stroke.points)
    w, h = x1 - x0, y1 - y0
    if w < 18 or h < 10:
        return None
    if min(w, h) / max(w, h) < 0.12:
        return None
    dist = math.hypot(stroke.points[0].x - stroke.points[-1].x, stroke.points[0].y - stroke.points[-1].y)
    if dist > 0.4 * max(w, h):
        return None
    return ellipse_from_bbox(x0, y0, x1, y1)


def pick_ellipse(strokes: list[Stroke]) -> tuple[Ellipse, int] | None:
    """Largest plausible ellipse, plus the stroke index it came from."""
    found: list[tuple[float, Ellipse, int]] = []
    for i, stroke in enumerate(strokes):
        ell = stroke_ellipse(stroke)
        if ell is None:
            continue
        found.append((ell.rx * ell.ry, ell, i))
    if not found:
        return None
    found.sort(reverse=True)
    _, ell, index = found[0]
    return ell, index


def _stroke_center(stroke: Stroke) -> tuple[float, float] | None:
    if stroke.tool == "ellipse" and stroke.ellipse is not None:
        return stroke.ellipse.cx, stroke.ellipse.cy
    if not stroke.points:
        return None
    x0, y0, x1, y1 = _bbox(stroke.points)
    return (x0 + x1) / 2, (y0 + y1) / 2


def _stroke_size(stroke: Stroke) -> tuple[float, float]:
    if stroke.tool == "ellipse" and stroke.ellipse is not None:
        return stroke.ellipse.rx * 2, stroke.ellipse.ry * 2
    if not stroke.points:
        return 0.0, 0.0
    x0, y0, x1, y1 = _bbox(stroke.points)
    return x1 - x0, y1 - y0


def _near_ellipse(x: float, y: float, ellipse: Ellipse) -> bool:
    dx = (x - ellipse.cx) / max(ellipse.rx, 1)
    dy = (y - ellipse.cy) / max(ellipse.ry, 1)
    dist = math.hypot(dx, dy)
    return 0.7 <= dist <= 3.2


def _looks_tall_mark(width: float, height: float) -> bool:
    if height < 10:
        return False
    return height >= width * 1.05


def has_exclamation(strokes: list[Stroke], ellipse: Ellipse, skip_index: int) -> bool:
    """A tall thin mark just outside the ellipse (the '!' drawn with the pen)."""
    others = [s for i, s in enumerate(strokes) if i != skip_index and s.tool == "pen"]
    for stroke in others:
        center = _stroke_center(stroke)
        if center is None:
            continue
        w, h = _stroke_size(stroke)
        if not _near_ellipse(center[0], center[1], ellipse):
            continue
        if ellipse.contains(center[0], center[1], pad=0.9):
            continue
        if _looks_tall_mark(w, h):
            return True

    # Line + dot drawn as two strokes: merge nearby leftover strokes.
    for i, a in enumerate(others):
        ca = _stroke_center(a)
        if ca is None:
            continue
        for b in others[i + 1 :]:
            cb = _stroke_center(b)
            if cb is None:
                continue
            if math.hypot(ca[0] - cb[0], ca[1] - cb[1]) > max(ellipse.ry, 24) * 1.4:
                continue
            mx, my = (ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2
            if not _near_ellipse(mx, my, ellipse):
                continue
            wa, ha = _stroke_size(a)
            wb, hb = _stroke_size(b)
            width = max(wa, wb)
            height = ha + hb
            if _looks_tall_mark(width, height):
                return True
    return False
