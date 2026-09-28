from dutext.compile import compile_side
from dutext.gestures import has_exclamation
from dutext.models import Ellipse, GenerateRequest, Point, Stroke
from dutext.pdf_text import page_words
from dutext.pipeline import apply_intent, recognize
from dutext.store import copy_project, load_sample, pdf_path, read_tex, write_tex


def test_circle_and_bang_bolds_sample_sentence() -> None:
    load_sample()
    compile_side("left")
    copy_project("left", "right")

    words = page_words(str(pdf_path("left")), 1)
    hyp = next(w for w in words if w.text == "hypothesis")
    line = [w for w in words if w.block == hyp.block and w.line == hyp.line]
    x0 = min(w.x0 for w in line)
    y0 = min(w.y0 for w in line)
    x1 = max(w.x1 for w in line)
    y1 = max(w.y1 for w in line)
    ellipse = Ellipse(
        cx=(x0 + x1) / 2,
        cy=(y0 + y1) / 2,
        rx=(x1 - x0) / 2 + 8,
        ry=(y1 - y0) / 2 + 6,
    )
    bang = Stroke(
        tool="pen",
        points=[
            Point(x=ellipse.cx + ellipse.rx + 10, y=ellipse.cy - ellipse.ry),
            Point(x=ellipse.cx + ellipse.rx + 12, y=ellipse.cy + ellipse.ry),
        ],
    )
    assert has_exclamation([Stroke(tool="ellipse", ellipse=ellipse), bang], ellipse, 0)

    request = GenerateRequest(
        page=1,
        page_width=595,
        page_height=842,
        strokes=[Stroke(tool="ellipse", ellipse=ellipse), bang],
    )
    intent = recognize(request, str(pdf_path("left")))
    assert "hypothesis" in intent.text
    updated = apply_intent(read_tex("left"), intent)
    assert r"\textbf{" in updated
    write_tex("right", updated)
    compile_side("right")
    assert pdf_path("right").exists()
