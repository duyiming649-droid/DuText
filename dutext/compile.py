from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dutext.config import COMPILE_TIMEOUT_SEC, TOOLS_DIR
from dutext.store import pdf_path, side_dir, tex_path


class CompileError(RuntimeError):
    def __init__(self, message: str, log: str = "") -> None:
        super().__init__(message)
        self.log = log


def _tectonic_exe() -> Path | None:
    local = TOOLS_DIR / "tectonic.exe"
    if local.exists():
        return local
    found = shutil.which("tectonic")
    return Path(found) if found else None


def engine_name() -> str:
    if _tectonic_exe() is not None:
        return "tectonic"
    for cmd in ("xelatex", "pdflatex"):
        if shutil.which(cmd):
            return cmd
    raise CompileError(
        "No LaTeX engine found. Place tectonic.exe in tools/ or install MiKTeX."
    )


def compile_side(side: str) -> Path:
    """Compile main.tex on one side. Returns the PDF path."""
    tex = tex_path(side)
    if not tex.exists():
        raise CompileError(f"missing {tex}")
    cwd = side_dir(side)
    log_path = cwd / "compile.log"
    engine = engine_name()

    if engine == "tectonic":
        cmd = [_tectonic_exe(), "--keep-logs", "--keep-intermediates", tex.name]
    else:
        cmd = [
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex.name,
        ]
    result = _run(cmd, cwd, log_path)

    pdf = pdf_path(side)
    if not pdf.exists():
        raise CompileError("compile finished but PDF was not produced", result)
    return pdf


def _run(cmd: list, cwd: Path, log_path: Path) -> str:
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMPILE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompileError(f"compile timed out after {COMPILE_TIMEOUT_SEC}s") from exc
    except FileNotFoundError as exc:
        raise CompileError(f"engine not executable: {cmd[0]}") from exc

    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log_path.write_text(log, encoding="utf-8")
    if proc.returncode != 0:
        tail = "\n".join(log.splitlines()[-40:])
        raise CompileError(f"LaTeX compile failed:\n{tail}", log)
    return log
