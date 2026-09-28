from dutext.apply_bold import apply_bold
from dutext.gestures import has_exclamation, pick_ellipse
from dutext.models import Ellipse, Point, Stroke


def test_apply_bold_wraps_first_match() -> None:
    tex = "Hello world.\nThe core hypothesis is that spatial marks win.\nBye."
    out, used = apply_bold(tex, "core hypothesis is that spatial marks win.")
    assert used == "core hypothesis is that spatial marks win."
    assert r"\textbf{core hypothesis is that spatial marks win.}" in out


def test_apply_bold_is_idempotent() -> None:
    tex = r"Say \textbf{hello there} please."
    out, used = apply_bold(tex, "hello there")
    assert out == tex
    assert used == "hello there"


def test_pick_ellipse_from_tool() -> None:
    ell = Ellipse(cx=100, cy=80, rx=40, ry=20)
    strokes = [Stroke(tool="ellipse", ellipse=ell)]
    picked = pick_ellipse(strokes)
    assert picked is not None
    assert picked[0].cx == 100


def test_exclamation_beside_ellipse() -> None:
    ell = Ellipse(cx=100, cy=80, rx=40, ry=20)
    bang = Stroke(
        tool="pen",
        points=[Point(x=155, y=60), Point(x=157, y=95), Point(x=156, y=108)],
    )
    assert has_exclamation([Stroke(tool="ellipse", ellipse=ell), bang], ell, 0)
