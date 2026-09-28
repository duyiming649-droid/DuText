from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dutext.apply_bold import ApplyError, apply_bold
from dutext.compile import CompileError, compile_side, engine_name
from dutext.config import STATIC_DIR
from dutext.llm import LLMError, REPAIR_TRIES, edit_tex, edit_tex_compose, perceive, perceive_compose, repair_tex
from dutext.models import GenerateRequest
from dutext.pipeline import GestureError, apply_compose, apply_intents, recognize
from dutext.secrets import get_api_key, key_is_set, set_api_key
from dutext.store import (
    backup_side,
    copy_project,
    import_tex_file,
    load_sample,
    pdf_path,
    read_tex,
    write_tex,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_ready()
    yield


app = FastAPI(title="DuText", version="0.1.0", lifespan=lifespan)


def _ensure_ready() -> None:
    from dutext.store import ensure_workspace, tex_path

    ensure_workspace()
    if not tex_path("left").exists():
        load_sample()
    if not pdf_path("left").exists():
        compile_side("left")
        copy_project("left", "right")


@app.get("/api/status")
def status() -> dict:
    _ensure_ready()
    left = pdf_path("left")
    right = pdf_path("right")

    def stamp(path: Path) -> int:
        return int(path.stat().st_mtime * 1000) if path.exists() else 0

    return {
        "engine": engine_name(),
        "left_pdf": left.exists(),
        "right_pdf": right.exists(),
        "rev": stamp(left) + stamp(right),
        "api_key_set": key_is_set(),
    }


@app.post("/api/sample")
def reset_sample() -> dict:
    load_sample()
    try:
        compile_side("left")
        copy_project("left", "right")
    except CompileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return status()


@app.post("/api/import")
async def import_tex(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(status_code=400, detail="Please upload a .tex file for this prototype.")
    raw = await file.read()
    tmp = Path(pdf_path("left").parent.parent / "_upload.tex")
    tmp.write_bytes(raw)
    try:
        import_tex_file(tmp)
        compile_side("left")
        copy_project("left", "right")
    except CompileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return status()


@app.get("/api/pdf/{side}")
def get_pdf(side: str, t: str = "") -> FileResponse:
    if side not in {"left", "right"}:
        raise HTTPException(status_code=404)
    path = pdf_path(side)
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not compiled yet")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/export/left")
def export_left() -> FileResponse:
    _ensure_ready()
    path = pdf_path("left")
    if not path.exists():
        raise HTTPException(status_code=404, detail="还没有可下载的 PDF。")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="dutext.pdf",
        headers={"Cache-Control": "no-store"},
    )


class KeyBody(BaseModel):
    key: str


@app.post("/api/key")
def save_key(body: KeyBody) -> dict:
    token = body.key.strip()
    if len(token) < 8:
        raise HTTPException(status_code=400, detail="这不像有效的 API Key。")
    set_api_key(token)
    return {"api_key_set": True}


@app.post("/api/generate")
def generate(request: GenerateRequest) -> dict:
    _ensure_ready()
    if not get_api_key():
        raise HTTPException(status_code=400, detail="请先在顶栏粘贴 DeepSeek API Key 并保存。")
    if not request.image_jpeg_base64.strip():
        raise HTTPException(status_code=400, detail="缺少带笔迹的页面截图，请刷新后再试。")
    try:
        original = read_tex("left")
        if request.mode == "compose":
            _reject_multi_page_compose()
            intents = perceive_compose(request, str(pdf_path("left")))
            try:
                new_tex = edit_tex_compose(original, intents, request)
            except LLMError:
                new_tex = apply_compose(original, intents, request)
        else:
            intents = []
            new_tex = None
            # Deterministic first: a clean circle + bang needs no model at all.
            try:
                intents = [recognize(request, str(pdf_path("left")))]
                new_tex = apply_intents(original, intents)
            except GestureError:
                intents = perceive(request.page, request.image_jpeg_base64, str(pdf_path("left")))
                try:
                    new_tex = edit_tex(original, intents)
                except LLMError:
                    new_tex = apply_intents(original, intents)
                for intent in intents:
                    if intent.kind == "emphasize" and intent.text:
                        try:
                            new_tex, used = apply_bold(new_tex, intent.text)
                            intent.text = used
                        except ApplyError:
                            pass
        write_tex("right", new_tex)
        _compile_right_with_repair()
    except (GestureError, LLMError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CompileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "intent": intents[0].model_dump() if intents else {},
        "intents": [item.model_dump() for item in intents],
        "status": status(),
    }


def _reject_multi_page_compose() -> None:
    """Compose rewrites one page into a whole document; a multi-page source would lose pages on accept."""
    with pymupdf.open(str(pdf_path("left"))) as doc:
        pages = doc.page_count
    if pages > 1:
        raise GestureError(f"画版目前只支持单页文档；这份文档有 {pages} 页。多页支持在路上了。")


def _compile_right_with_repair() -> None:
    last_error: CompileError | None = None
    for attempt in range(REPAIR_TRIES + 1):
        try:
            compile_side("right")
            return
        except CompileError as exc:
            last_error = exc
            if attempt >= REPAIR_TRIES:
                break
            write_tex("right", repair_tex(read_tex("right"), exc.log or str(exc)))
    assert last_error is not None
    raise last_error


@app.post("/api/accept")
def accept() -> dict:
    """Right proposal becomes the new left (current) document."""
    backup_side("left")
    copy_project("right", "left")
    return status()


@app.post("/api/reject")
def reject() -> dict:
    """Discard the proposal: copy left source back onto the right."""
    copy_project("left", "right")
    return status()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
