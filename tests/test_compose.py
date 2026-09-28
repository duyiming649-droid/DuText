from dutext.models import GenerateRequest, InstructionNote, Intent, Point, RectBox, Stroke
from dutext.pdf_text import WordBox, words_inside_rect
from dutext.pipeline import apply_compose, intents_from_compose_strokes


def test_words_inside_rect_selects_centers() -> None:
    words = [
        WordBox(0, 0, 10, 10, "Hello", 0, 0, 0),
        WordBox(50, 50, 60, 60, "Skip", 0, 1, 0),
    ]
    got = words_inside_rect(words, RectBox(x=0, y=0, w=20, h=20))
    assert [item.text for item in got] == ["Hello"]


def test_rectbox_normalizes_negative_size() -> None:
    box = RectBox(x=10, y=10, w=-8, h=-6).normalized()
    assert box.x == 2
    assert box.y == 4
    assert box.w == 8
    assert box.h == 6


def test_place_intent_from_rects(monkeypatch) -> None:
    words = [
        WordBox(10, 10, 40, 20, "hello", 0, 0, 0),
        WordBox(42, 10, 80, 20, "world", 0, 0, 1),
    ]
    monkeypatch.setattr("dutext.pipeline.page_words", lambda *args, **kwargs: words)
    request = GenerateRequest(
        page=1,
        page_width=595,
        page_height=842,
        mode="compose",
        strokes=[
            Stroke(
                tool="rect",
                side="left",
                group=0,
                color="#dc2626",
                rect=RectBox(x=8, y=8, w=80, h=20),
            ),
            Stroke(
                tool="arrow",
                group=0,
                color="#dc2626",
                from_side="left",
                to_side="right",
                points=[Point(x=88, y=15)],
                to_point=Point(x=140, y=440),
            ),
            Stroke(
                tool="rect",
                side="right",
                group=0,
                color="#dc2626",
                rect=RectBox(x=40, y=400, w=200, h=80),
            ),
            Stroke(
                tool="black",
                side="right",
                group=3,
                points=[Point(x=40, y=800), Point(x=500, y=800)],
            ),
        ],
        notes=[InstructionNote(group=0, note="keep 12pt")],
    )
    intents = intents_from_compose_strokes(request, "dummy.pdf")
    place = next(item for item in intents if item.kind == "place")
    assert "hello" in place.text
    assert "world" in place.text
    assert place.dest_rect is not None
    assert place.dest_rect.w == 200
    assert place.note == "keep 12pt"
    assert any(item.kind == "template" for item in intents)


def test_apply_compose_black_only_keeps_body() -> None:
    tex = "\\documentclass{article}\\begin{document}Hi there\\end{document}"
    request = GenerateRequest(
        page=1,
        page_width=595,
        page_height=842,
        mode="compose",
        strokes=[
            Stroke(
                tool="black",
                side="right",
                group=3,
                points=[Point(x=40, y=800), Point(x=500, y=802)],
            )
        ],
    )
    intent = Intent(kind="template", page=1, text="", group=3, color="#111111")
    out = apply_compose(tex, [intent], request)
    assert "Hi there" in out
    assert "tikzpicture" in out
    assert "--" in out
