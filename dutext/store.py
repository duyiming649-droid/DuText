from __future__ import annotations

import shutil
import time
from pathlib import Path

from dutext.config import DATA_DIR, SAMPLES_DIR, WORKSPACE

TEX_NAME = "main.tex"
PDF_NAME = "main.pdf"
HISTORY_DIR = DATA_DIR / "history"
HISTORY_KEEP = 5


def left_dir() -> Path:
    return WORKSPACE / "left"


def right_dir() -> Path:
    return WORKSPACE / "right"


def side_dir(side: str) -> Path:
    if side not in {"left", "right"}:
        raise ValueError(f"unknown side {side}")
    return WORKSPACE / side


def tex_path(side: str) -> Path:
    return side_dir(side) / TEX_NAME


def pdf_path(side: str) -> Path:
    return side_dir(side) / PDF_NAME


def read_tex(side: str) -> str:
    return tex_path(side).read_text(encoding="utf-8")


def write_tex(side: str, source: str) -> None:
    tex_path(side).write_text(source, encoding="utf-8")


def ensure_workspace() -> None:
    left_dir().mkdir(parents=True, exist_ok=True)
    right_dir().mkdir(parents=True, exist_ok=True)


def copy_project(src_side: str, dst_side: str) -> None:
    src = side_dir(src_side)
    dst = side_dir(dst_side)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def backup_side(side: str) -> Path | None:
    """Snapshot a side into data/history before it gets overwritten. Keeps the newest few."""
    if not tex_path(side).exists():
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    dst = HISTORY_DIR / f"{side}-{time.strftime('%Y%m%d-%H%M%S')}"
    if dst.exists():
        return None
    shutil.copytree(side_dir(side), dst)
    backups = sorted(HISTORY_DIR.glob(f"{side}-*"))
    for old in backups[:-HISTORY_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return dst


def load_tex_into_both(tex: str) -> None:
    """Reset left and right to the same source. PDFs are compiled by the caller."""
    ensure_workspace()
    write_tex("left", tex)
    copy_project("left", "right")


def load_sample() -> None:
    sample = SAMPLES_DIR / "demo.tex"
    load_tex_into_both(sample.read_text(encoding="utf-8"))


def import_tex_file(path: Path) -> None:
    load_tex_into_both(path.read_text(encoding="utf-8"))
