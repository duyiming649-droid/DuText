from typing import Literal

from pydantic import BaseModel, Field

ToolName = Literal["pen", "ellipse", "rect", "arrow", "black"]
IntentKind = Literal["emphasize", "place", "template"]
SideName = Literal["left", "right"]


class Point(BaseModel):
    x: float
    y: float


class Ellipse(BaseModel):
    cx: float
    cy: float
    rx: float
    ry: float

    def contains(self, x: float, y: float, pad: float = 1.15) -> bool:
        rx = max(self.rx * pad, 1.0)
        ry = max(self.ry * pad, 1.0)
        return ((x - self.cx) / rx) ** 2 + ((y - self.cy) / ry) ** 2 <= 1.0


class RectBox(BaseModel):
    x: float
    y: float
    w: float
    h: float

    def normalized(self) -> "RectBox":
        x, y, w, h = self.x, self.y, self.w, self.h
        if w < 0:
            x += w
            w = -w
        if h < 0:
            y += h
            h = -h
        return RectBox(x=x, y=y, w=w, h=h)


class Stroke(BaseModel):
    """One overlay mark, stored in PDF space with origin at the top-left."""

    tool: ToolName
    points: list[Point] = Field(default_factory=list)
    ellipse: Ellipse | None = None
    rect: RectBox | None = None
    side: SideName = "left"
    from_side: SideName = "left"
    to_side: SideName | None = None
    to_point: Point | None = None
    group: int = 0
    color: str = ""


class Intent(BaseModel):
    """Stable shape for later gestures (move, group, strike, ...)."""

    kind: IntentKind
    page: int
    text: str
    ellipse: Ellipse | None = None
    source_rect: RectBox | None = None
    dest_rect: RectBox | None = None
    summary: str = ""
    group: int = 0
    color: str = ""
    note: str = ""


class InstructionNote(BaseModel):
    group: int = 0
    note: str = ""


class GenerateRequest(BaseModel):
    page: int = Field(ge=1)
    page_width: float
    page_height: float
    strokes: list[Stroke] = Field(default_factory=list)
    image_jpeg_base64: str = ""
    mode: Literal["layout", "compose"] = "layout"
    notes: list[InstructionNote] = Field(default_factory=list)
