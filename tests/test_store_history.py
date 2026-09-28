from dutext import store


class FakeTime:
    """Deterministic strftime so successive backups get distinct stamps."""

    def __init__(self) -> None:
        self.n = 0

    def strftime(self, _fmt: str) -> str:
        self.n += 1
        return f"20260101-0000{self.n:02d}"


def test_backup_side_keeps_recent_five(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "workspace"
    (ws / "left").mkdir(parents=True)
    (ws / "left" / "main.tex").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(store, "WORKSPACE", ws)
    monkeypatch.setattr(store, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(store, "time", FakeTime())

    first = store.backup_side("left")
    assert first is not None and (first / "main.tex").exists()

    for i in range(6):
        (ws / "left" / "main.tex").write_text(f"v{i}", encoding="utf-8")
        store.backup_side("left")

    backups = sorted((tmp_path / "history").glob("left-*"))
    assert len(backups) == 5
    assert (backups[-1] / "main.tex").read_text(encoding="utf-8") == "v5"


def test_backup_side_missing_tex_is_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(store, "HISTORY_DIR", tmp_path / "history")
    assert store.backup_side("left") is None
    assert not (tmp_path / "history").exists()
