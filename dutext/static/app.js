/* Dual-pane PDF viewer with a drawing overlay.
   Layout mode: ellipse + pen on the left, up to three color instructions.
   Compose mode: left original + right blank canvas, rect/arrow/black, then 完成 → 排一版. */

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const MAX_INSTRUCTIONS = 3;
const COLORS = [
  { id: "red", stroke: "#dc2626", name: "红" },
  { id: "yellow", stroke: "#ca8a04", name: "黄" },
  { id: "blue", stroke: "#2563eb", name: "蓝" },
];
const BLACK = { id: "black", stroke: "#111111", name: "黑" };

const state = {
  tool: "ellipse",
  page: 1,
  pageCount: 1,
  rev: 0,
  history: [],
  cursor: 0,
  drawing: null,
  wheelLock: false,
  ui: "layout",
  fromCompose: false,
  sidebarCollapsed: false,
  promptsOpen: false,
  highlightGroup: null,
  left: { pdf: null, page: null, viewport: null },
  right: { pdf: null, page: null, viewport: null },
};

const els = {
  overlayLeft: document.getElementById("overlay-left"),
  overlayRight: document.getElementById("overlay-right"),
  overlayBridge: document.getElementById("overlay-bridge"),
  pdfLeft: document.getElementById("pdf-left"),
  pdfRight: document.getElementById("pdf-right"),
  sheetLeft: document.getElementById("sheet-left"),
  sheetRight: document.getElementById("sheet-right"),
  core: document.getElementById("core"),
  status: document.getElementById("status"),
  pageLabel: document.getElementById("page-label"),
  file: document.getElementById("file-input"),
  apiKey: document.getElementById("api-key"),
  keyState: document.getElementById("key-state"),
  undo: document.getElementById("btn-undo"),
  redo: document.getElementById("btn-redo"),
  inkDot: document.getElementById("ink-dot"),
  inkLabel: document.getElementById("ink-label"),
  scrollLeft: document.getElementById("scroll-left"),
  scrollRight: document.getElementById("scroll-right"),
  leftTitle: document.getElementById("left-title"),
  leftHint: document.getElementById("left-hint"),
  rightTitle: document.getElementById("right-title"),
  rightHint: document.getElementById("right-hint"),
  btnCompose: document.getElementById("btn-compose"),
  btnSidebar: document.getElementById("btn-sidebar"),
  fab: document.getElementById("ai-fab"),
};

function setStatus(text, kind) {
  els.status.textContent = text;
  els.status.classList.remove("is-ok", "is-bad", "is-busy");
  if (kind) els.status.classList.add(kind);
}

function isComposeView() {
  return state.ui === "compose" || state.ui === "ready" || state.ui === "result";
}

function isBlankRight() {
  return state.ui === "compose" || state.ui === "ready";
}

function replay() {
  const strokes = [];
  let sealed = 0;
  for (let i = 0; i < state.cursor; i += 1) {
    const cmd = state.history[i];
    if (cmd.type === "stroke") {
      if (cmd.stroke.tool === "black") {
        strokes.push({
          ...cmd.stroke,
          group: 3,
          color: BLACK.stroke,
          colorName: BLACK.id,
        });
        continue;
      }
      if (sealed >= MAX_INSTRUCTIONS) continue;
      const color = COLORS[sealed];
      strokes.push({
        ...cmd.stroke,
        group: sealed,
        color: color.stroke,
        colorName: color.id,
      });
    } else if (cmd.type === "commit") {
      const hasOpen = strokes.some((s) => s.group === sealed);
      if (hasOpen && sealed < MAX_INSTRUCTIONS) sealed += 1;
    }
  }
  return {
    strokes,
    sealed,
    canDraw: sealed < MAX_INSTRUCTIONS,
    activeGroup: Math.min(sealed, MAX_INSTRUCTIONS - 1),
  };
}

function currentStrokes() {
  return replay().strokes;
}

function pushCommand(cmd) {
  state.history = state.history.slice(0, state.cursor);
  state.history.push(cmd);
  state.cursor = state.history.length;
}

function resetInk() {
  state.history = [];
  state.cursor = 0;
  state.drawing = null;
  drawOverlay();
  updateChrome();
}

function undo() {
  if (state.cursor <= 0) return;
  state.cursor -= 1;
  drawOverlay();
  updateChrome();
}

function redo() {
  if (state.cursor >= state.history.length) return;
  state.cursor += 1;
  drawOverlay();
  updateChrome();
}

function commitInstruction() {
  const snap = replay();
  if (!snap.canDraw) {
    setStatus("这一轮已经有三条彩色指令，请点「完成」或「排一版」。黑笔仍可继续画。", "is-bad");
    return;
  }
  const hasOpen = snap.strokes.some((s) => s.group === snap.sealed);
  if (!hasOpen) {
    setStatus("当前颜色还没有笔画。先画完再确认这条指令。", "is-bad");
    return;
  }
  pushCommand({ type: "commit" });
  const after = replay();
  drawOverlay();
  updateChrome();
  if (!after.canDraw) {
    setStatus("三条彩色指令已满。黑笔版面仍可再画。可以点「完成」。", "is-ok");
  } else {
    const next = COLORS[after.sealed];
    setStatus(`第 ${after.sealed} 条已确认。下一笔用${next.name}色。`, "is-ok");
  }
}

function setTool(name) {
  state.tool = name;
  document.querySelectorAll("[data-tool]").forEach((btn) => {
    btn.classList.toggle("is-on", btn.dataset.tool === name);
  });
  updateChrome();
}

function syncBodyClass() {
  document.body.classList.toggle("is-compose", isComposeView());
  document.body.classList.toggle("is-drawing", state.ui === "compose");
  document.body.classList.toggle("is-ready", state.ui === "ready");
  document.body.classList.toggle("showing-result", state.ui === "result");
  document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  document.body.classList.toggle("prompts-open", state.promptsOpen);
}

function relayout() {
  syncBodyClass();
  updateChrome();
  window.requestAnimationFrame(() => {
    if (state.left.pdf) renderBoth();
  });
}

function updateChrome() {
  const snap = replay();
  els.undo.disabled = state.cursor <= 0;
  els.redo.disabled = state.cursor >= state.history.length;
  els.btnCompose.classList.toggle("is-on", isComposeView());
  els.btnSidebar.textContent = state.sidebarCollapsed ? "›" : "‹";

  if (state.tool === "black") {
    els.inkDot.style.background = BLACK.stroke;
    els.inkLabel.textContent = "指令 4／4 · 黑笔版面";
  } else {
    const color = COLORS[snap.canDraw ? snap.sealed : MAX_INSTRUCTIONS - 1];
    els.inkDot.style.background = color.stroke;
    if (!snap.canDraw) {
      els.inkLabel.textContent = isComposeView() ? "彩色 3／3 · 已满（黑笔仍可用）" : "指令 3／3 · 已满";
    } else {
      els.inkLabel.textContent = `指令 ${snap.sealed + 1}／3 · ${color.name}`;
    }
  }

  if (state.ui === "compose") {
    els.leftTitle.textContent = "原文";
    els.leftHint.textContent = "矩形圈出要移动的段落；右键或 Ctrl+滚轮确认一条彩色指令。黑笔用来画版面。";
    els.rightTitle.textContent = "空白画布";
    els.rightHint.textContent = "同色矩形是目标位置；箭头从左边指过来。黑笔可画实线、框线等模板。";
  } else if (state.ui === "ready") {
    els.leftTitle.textContent = "画稿";
    els.leftHint.textContent = "画画已完成。点「排一版」生成右边。";
    els.rightTitle.textContent = "待生成";
    els.rightHint.textContent = "生成后可以收下或打回。";
  } else {
    els.leftTitle.textContent = "当前稿";
    els.leftHint.textContent = "右键或 Ctrl+滚轮结束一条指令；普通滚轮上下滑动。一次最多三条。";
    els.rightTitle.textContent = "提案";
    els.rightHint.textContent = "编译后的结果。不满意就打回。";
  }
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function cssSize(canvas, width, height) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(width * dpr));
  canvas.height = Math.max(1, Math.floor(height * dpr));
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function pageSize(page) {
  const view = page.view;
  return { width: view[2] - view[0], height: view[3] - view[1], view };
}

function canvasToPdf(x, y, viewport, page) {
  const [pdfX, pdfY] = viewport.convertToPdfPoint(x, y);
  const { height, view } = pageSize(page);
  return { x: pdfX - view[0], y: height - (pdfY - view[1]) };
}

function pdfToCanvas(p, viewport, page) {
  const { height, view } = pageSize(page);
  const pdfX = p.x + view[0];
  const pdfY = view[1] + (height - p.y);
  const [x, y] = viewport.convertToViewportPoint(pdfX, pdfY);
  return { x, y };
}

function overlayFromSide(side) {
  return side === "left" ? els.overlayLeft : els.overlayRight;
}

function hitSide(clientX, clientY) {
  for (const side of ["left", "right"]) {
    const overlay = overlayFromSide(side);
    const rect = overlay.getBoundingClientRect();
    if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
      return side;
    }
  }
  return null;
}

function clientToPdf(clientX, clientY, side) {
  const overlay = overlayFromSide(side);
  const slot = state[side];
  const rect = overlay.getBoundingClientRect();
  const x = ((clientX - rect.left) * overlay.clientWidth) / Math.max(rect.width, 1);
  const y = ((clientY - rect.top) * overlay.clientHeight) / Math.max(rect.height, 1);
  return canvasToPdf(x, y, slot.viewport, slot.page);
}

async function loadPdfs() {
  const info = await api("/api/status");
  state.rev = info.rev;
  setKeyState(info.api_key_set);
  const query = `?t=${info.rev}`;
  const leftTask = pdfjsLib.getDocument(`/api/pdf/left${query}`).promise;
  const rightTask = pdfjsLib.getDocument(`/api/pdf/right${query}`).promise;
  state.left.pdf = await leftTask;
  state.right.pdf = await rightTask;
  state.pageCount = state.left.pdf.numPages;
  if (state.page > state.pageCount) state.page = state.pageCount;
  els.pageLabel.textContent = `${state.page} / ${state.pageCount}`;
  await renderBoth();
}

async function renderBoth() {
  await renderPane("left");
  await renderPane("right");
  drawOverlay();
  updateChrome();
}

async function renderPane(side) {
  const slot = state[side];
  const canvas = side === "left" ? els.pdfLeft : els.pdfRight;
  const sheet = side === "left" ? els.sheetLeft : els.sheetRight;
  const overlay = overlayFromSide(side);
  const host = canvas.parentElement.parentElement;
  const available = Math.max(280, host.clientWidth - 36);

  if (side === "right" && isBlankRight()) {
    const src = state.left;
    if (!src.page) return;
    const unscaled = src.page.getViewport({ scale: 1 });
    const scale = available / unscaled.width;
    slot.page = src.page;
    slot.viewport = src.page.getViewport({ scale });
    const ctx = cssSize(canvas, slot.viewport.width, slot.viewport.height);
    sheet.style.width = `${slot.viewport.width}px`;
    sheet.style.height = `${slot.viewport.height}px`;
    ctx.fillStyle = "#fbfaf7";
    ctx.fillRect(0, 0, slot.viewport.width, slot.viewport.height);
    cssSize(overlay, slot.viewport.width, slot.viewport.height);
    return;
  }

  slot.page = await slot.pdf.getPage(state.page);
  const unscaled = slot.page.getViewport({ scale: 1 });
  const scale = available / unscaled.width;
  slot.viewport = slot.page.getViewport({ scale });
  const ctx = cssSize(canvas, slot.viewport.width, slot.viewport.height);
  sheet.style.width = `${slot.viewport.width}px`;
  sheet.style.height = `${slot.viewport.height}px`;
  await slot.page.render({ canvasContext: ctx, viewport: slot.viewport }).promise;
  cssSize(overlay, slot.viewport.width, slot.viewport.height);
}

function visibleStrokes() {
  const live = currentStrokes().slice();
  if (state.drawing) live.push(state.drawing);
  return live;
}

function withGlow(ctx, stroke, paint) {
  const hot = state.highlightGroup != null && stroke.group === state.highlightGroup;
  ctx.save();
  ctx.strokeStyle = stroke.color || COLORS[0].stroke;
  ctx.fillStyle = ctx.strokeStyle;
  ctx.lineWidth = hot ? 3.2 : 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  if (hot) {
    ctx.shadowColor = stroke.color || BLACK.stroke;
    ctx.shadowBlur = 18;
  }
  paint();
  if (hot) {
    ctx.shadowBlur = 0;
    ctx.lineWidth = 2;
    paint();
  }
  ctx.restore();
}

function paintStroke(ctx, stroke, viewport, page) {
  if ((stroke.tool === "ellipse" || stroke.ellipse) && stroke.ellipse && stroke.tool !== "rect") {
    const e = stroke.ellipse;
    const c = pdfToCanvas({ x: e.cx, y: e.cy }, viewport, page);
    const r = pdfToCanvas({ x: e.cx + e.rx, y: e.cy + e.ry }, viewport, page);
    ctx.beginPath();
    ctx.ellipse(c.x, c.y, Math.abs(r.x - c.x), Math.abs(r.y - c.y), 0, 0, Math.PI * 2);
    ctx.stroke();
    return;
  }
  if ((stroke.tool === "rect" || stroke.rect) && stroke.rect) {
    const box = stroke.rect;
    const a = pdfToCanvas({ x: box.x, y: box.y }, viewport, page);
    const b = pdfToCanvas({ x: box.x + box.w, y: box.y + box.h }, viewport, page);
    ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
    return;
  }
  if (!stroke.points.length) return;
  ctx.beginPath();
  stroke.points.forEach((p, i) => {
    const c = pdfToCanvas(p, viewport, page);
    if (i === 0) ctx.moveTo(c.x, c.y);
    else ctx.lineTo(c.x, c.y);
  });
  ctx.stroke();
}

function drawArrowHead(ctx, x1, y1, x2, y2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const len = 12;
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - len * Math.cos(angle - 0.4), y2 - len * Math.sin(angle - 0.4));
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - len * Math.cos(angle + 0.4), y2 - len * Math.sin(angle + 0.4));
  ctx.stroke();
}

function sheetPdfToBridge(side, pdfPt) {
  const slot = state[side];
  const overlay = overlayFromSide(side);
  const coreRect = els.core.getBoundingClientRect();
  const ovRect = overlay.getBoundingClientRect();
  const c = pdfToCanvas(pdfPt, slot.viewport, slot.page);
  const scaleX = ovRect.width / Math.max(overlay.clientWidth, 1);
  const scaleY = ovRect.height / Math.max(overlay.clientHeight, 1);
  return {
    x: ovRect.left - coreRect.left + c.x * scaleX,
    y: ovRect.top - coreRect.top + c.y * scaleY,
  };
}

function drawOverlay() {
  drawSheetOverlay("left");
  drawSheetOverlay("right");
  drawBridge();
}

function drawSheetOverlay(side) {
  const canvas = overlayFromSide(side);
  const slot = state[side];
  if (!slot.viewport || !slot.page) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  if (side === "right" && state.ui === "result") return;
  for (const stroke of visibleStrokes()) {
    if (stroke.tool === "arrow") continue;
    if ((stroke.side || "left") !== side) continue;
    withGlow(ctx, stroke, () => paintStroke(ctx, stroke, slot.viewport, slot.page));
  }
}

function drawBridge() {
  const canvas = els.overlayBridge;
  if (!canvas || !isComposeView() || state.ui === "result") return;
  const width = els.core.clientWidth;
  const height = els.core.clientHeight;
  const ctx = cssSize(canvas, width, height);
  ctx.clearRect(0, 0, width, height);
  for (const stroke of visibleStrokes()) {
    if (stroke.tool !== "arrow" || !stroke.points.length || !stroke.to_point) continue;
    const fromSide = stroke.from_side || "left";
    const toSide = stroke.to_side || "right";
    if (!state[fromSide].viewport || !state[toSide].viewport) continue;
    const a = sheetPdfToBridge(fromSide, stroke.points[0]);
    const b = sheetPdfToBridge(toSide, stroke.to_point);
    withGlow(ctx, stroke, () => drawArrowHead(ctx, a.x, a.y, b.x, b.y));
  }
}

function colorForDraw(snap, tool) {
  if (tool === "black") return BLACK;
  return COLORS[snap.sealed];
}

function onArrowMove(event) {
  moveDraw(event);
}

function onArrowUp(event) {
  window.removeEventListener("pointermove", onArrowMove);
  window.removeEventListener("pointerup", onArrowUp);
  window.removeEventListener("pointercancel", onArrowUp);
  endDraw(event);
}

function startDraw(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const side = hitSide(event.clientX, event.clientY);
  if (!side) return;
  if (!isComposeView() && side === "right") return;
  if (state.ui === "result") return;
  const slot = state[side];
  if (!slot.viewport || !slot.page) return;

  const snap = replay();
  const tool = state.tool;
  if (tool !== "black" && !snap.canDraw) {
    setStatus("这一轮已经有三条彩色指令。黑笔仍可画版面，或点「完成」。", "is-bad");
    return;
  }

  const pdf = clientToPdf(event.clientX, event.clientY, side);
  const color = colorForDraw(snap, tool);
  const group = tool === "black" ? 3 : snap.sealed;
  const base = {
    tool,
    points: [pdf],
    ellipse: null,
    rect: null,
    side,
    from_side: side,
    to_side: side,
    to_point: null,
    group,
    color: color.stroke,
    colorName: color.id,
  };

  if (tool === "ellipse") {
    base.ellipse = { cx: pdf.x, cy: pdf.y, rx: 1, ry: 1 };
  } else if (tool === "rect") {
    base.rect = { x: pdf.x, y: pdf.y, w: 1, h: 1 };
  } else if (tool === "arrow") {
    base.to_point = pdf;
    state.drawing = base;
    drawOverlay();
    window.addEventListener("pointermove", onArrowMove);
    window.addEventListener("pointerup", onArrowUp);
    window.addEventListener("pointercancel", onArrowUp);
    return;
  }

  state.drawing = base;
  event.currentTarget.setPointerCapture(event.pointerId);
  drawOverlay();
}

function moveDraw(event) {
  if (!state.drawing) return;
  const stroke = state.drawing;
  if (stroke.tool === "arrow") {
    const side = hitSide(event.clientX, event.clientY) || stroke.to_side || stroke.side;
    if (!state[side] || !state[side].viewport) return;
    stroke.to_side = side;
    stroke.to_point = clientToPdf(event.clientX, event.clientY, side);
    drawOverlay();
    return;
  }
  const side = stroke.side || "left";
  if (!state[side].viewport) return;
  const pdf = clientToPdf(event.clientX, event.clientY, side);
  if (stroke.tool === "ellipse") {
    const origin = stroke.points[0];
    stroke.ellipse = {
      cx: (origin.x + pdf.x) / 2,
      cy: (origin.y + pdf.y) / 2,
      rx: Math.abs(pdf.x - origin.x) / 2,
      ry: Math.abs(pdf.y - origin.y) / 2,
    };
  } else if (stroke.tool === "rect") {
    const origin = stroke.points[0];
    stroke.rect = {
      x: origin.x,
      y: origin.y,
      w: pdf.x - origin.x,
      h: pdf.y - origin.y,
    };
  } else {
    stroke.points.push(pdf);
  }
  drawOverlay();
}

function normalizeRect(rect) {
  const box = { ...rect };
  if (box.w < 0) {
    box.x += box.w;
    box.w = -box.w;
  }
  if (box.h < 0) {
    box.y += box.h;
    box.h = -box.h;
  }
  return box;
}

function endDraw(event) {
  if (!state.drawing) return;
  const stroke = state.drawing;
  state.drawing = null;
  if (stroke.tool === "ellipse") {
    if (!stroke.ellipse || stroke.ellipse.rx < 6 || stroke.ellipse.ry < 4) {
      drawOverlay();
      return;
    }
  } else if (stroke.tool === "rect") {
    stroke.rect = normalizeRect(stroke.rect);
    if (stroke.rect.w < 8 || stroke.rect.h < 8) {
      drawOverlay();
      return;
    }
  } else if (stroke.tool === "arrow") {
    if (!stroke.to_point || !stroke.points.length) {
      drawOverlay();
      return;
    }
    const dx = stroke.to_point.x - stroke.points[0].x;
    const dy = stroke.to_point.y - stroke.points[0].y;
    const far = Math.hypot(dx, dy) > 12 || stroke.from_side !== stroke.to_side;
    if (!far) {
      drawOverlay();
      return;
    }
  } else if (stroke.points.length < 2) {
    drawOverlay();
    return;
  }
  pushCommand({ type: "stroke", stroke });
  drawOverlay();
  updateChrome();
}

function setKeyState(configured) {
  els.keyState.textContent = configured ? "已保存" : "未配置";
  els.keyState.classList.toggle("is-on", configured);
}

function snapshotSheet(side) {
  const pdf = side === "left" ? els.pdfLeft : els.pdfRight;
  const overlay = overlayFromSide(side);
  const out = document.createElement("canvas");
  out.width = pdf.width;
  out.height = pdf.height;
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#fbfaf7";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(pdf, 0, 0);
  ctx.drawImage(overlay, 0, 0);
  return out;
}

function cssToBitmap(canvas, x, y) {
  return {
    x: x * (canvas.width / Math.max(canvas.clientWidth, 1)),
    y: y * (canvas.height / Math.max(canvas.clientHeight, 1)),
  };
}

function captureLeftPage() {
  const out = snapshotSheet("left");
  return out.toDataURL("image/jpeg", 0.86).replace(/^data:image\/jpeg;base64,/, "");
}

function paintBlankWithStrokes(side) {
  const template = side === "left" ? els.pdfLeft : els.pdfRight;
  const slot = state[side];
  const out = document.createElement("canvas");
  out.width = template.width;
  out.height = template.height;
  const ctx = out.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#fbfaf7";
  ctx.fillRect(0, 0, template.clientWidth, template.clientHeight);
  if (!slot.viewport || !slot.page) return out;
  for (const stroke of currentStrokes()) {
    if (stroke.tool === "arrow") continue;
    if ((stroke.side || "left") !== side) continue;
    withGlow(ctx, { ...stroke, group: -1 }, () => paintStroke(ctx, stroke, slot.viewport, slot.page));
  }
  return out;
}

function captureComposePage() {
  const left = snapshotSheet("left");
  const right = state.ui === "result" ? paintBlankWithStrokes("right") : snapshotSheet("right");
  const gap = 28;
  const labelH = 28;
  const out = document.createElement("canvas");
  out.width = left.width + gap + right.width;
  out.height = Math.max(left.height, right.height) + labelH;
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#ebe4d8";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.fillStyle = "#1f1b16";
  ctx.font = "18px sans-serif";
  ctx.fillText("LEFT source", 8, 20);
  ctx.fillText("RIGHT blank canvas", left.width + gap + 8, 20);
  ctx.drawImage(left, 0, labelH);
  ctx.drawImage(right, left.width + gap, labelH);

  for (const stroke of currentStrokes()) {
    if (stroke.tool !== "arrow" || !stroke.points.length || !stroke.to_point) continue;
    const fromSide = stroke.from_side || "left";
    const toSide = stroke.to_side || "right";
    const fromCanvas = fromSide === "left" ? left : right;
    const toCanvas = toSide === "left" ? left : right;
    const aCss = pdfToCanvas(stroke.points[0], state[fromSide].viewport, state[fromSide].page);
    const bCss = pdfToCanvas(stroke.to_point, state[toSide].viewport, state[toSide].page);
    const a = cssToBitmap(fromCanvas, aCss.x, aCss.y);
    const b = cssToBitmap(toCanvas, bCss.x, bCss.y);
    const x1 = (fromSide === "left" ? 0 : left.width + gap) + a.x;
    const y1 = labelH + a.y;
    const x2 = (toSide === "left" ? 0 : left.width + gap) + b.x;
    const y2 = labelH + b.y;
    ctx.strokeStyle = stroke.color || COLORS[0].stroke;
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    drawArrowHead(ctx, x1, y1, x2, y2);
  }
  return out.toDataURL("image/jpeg", 0.86).replace(/^data:image\/jpeg;base64,/, "");
}

function collectNotes() {
  return [0, 1, 2, 3].map((group) => {
    const box = document.querySelector(`textarea[data-group="${group}"]`);
    return { group, note: box ? box.value.trim() : "" };
  });
}

async function generate() {
  if (!state.left.page) return;
  if (state.ui === "compose") {
    setStatus("请先点「完成」，再点「排一版」。", "is-bad");
    return;
  }
  const { width, height } = pageSize(state.left.page);
  const compose = state.fromCompose && state.ui !== "layout";
  setStatus("正在把带笔迹的页面发给 DeepSeek…", "is-busy");
  try {
    const result = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page: state.page,
        page_width: width,
        page_height: height,
        strokes: currentStrokes(),
        image_jpeg_base64: compose ? captureComposePage() : captureLeftPage(),
        mode: compose ? "compose" : "layout",
        notes: collectNotes(),
      }),
    });
    const intents = result.intents || (result.intent ? [result.intent] : []);
    const summary =
      intents.map((item) => item.summary).filter(Boolean).join("；") ||
      (intents[0] && intents[0].text ? `将加粗：${intents.map((i) => i.text).join(" / ")}` : "");
    if (compose) state.ui = "result";
    syncBodyClass();
    setStatus(summary || "已更新右边的提案。", "is-ok");
    await loadPdfs();
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
}

async function goPage(next) {
  const target = state.page + next;
  if (target < 1 || target > state.pageCount) return;
  state.page = target;
  await renderBoth();
  els.pageLabel.textContent = `${state.page} / ${state.pageCount}`;
}

function onCommitWheel(event) {
  if (!event.ctrlKey) return;
  event.preventDefault();
  if (state.wheelLock) return;
  state.wheelLock = true;
  commitInstruction();
  window.setTimeout(() => {
    state.wheelLock = false;
  }, 450);
}

function enterCompose() {
  if (state.pageCount > 1) {
    setStatus(`画版目前只支持单页文档；这份文档有 ${state.pageCount} 页，收下提案会吞掉其他页。`, "is-bad");
    return;
  }
  state.ui = "compose";
  state.fromCompose = true;
  state.promptsOpen = false;
  if (state.tool === "ellipse") setTool("rect");
  else setTool(state.tool);
  setStatus("左边原文，右边空白画布。矩形圈文字，箭头拉到右边同色框；黑笔可选。画完点「完成」。");
  relayout();
}

function finishCompose() {
  state.ui = "ready";
  state.promptsOpen = false;
  state.highlightGroup = null;
  document.querySelectorAll(".prompt-card").forEach((card) => card.classList.remove("is-hot"));
  setStatus("画完了。左边是你的画稿，点「排一版」生成右边。", "is-ok");
  relayout();
}

async function downloadLeft() {
  try {
    const res = await fetch(`/api/export/left?t=${state.rev || Date.now()}`);
    if (!res.ok) throw new Error("下载失败。");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "dutext.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("已开始下载左边当前稿。", "is-ok");
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
}

document.querySelectorAll("[data-tool]").forEach((btn) => {
  btn.addEventListener("click", () => setTool(btn.dataset.tool));
});

document.getElementById("btn-save-key").addEventListener("click", saveKey);
els.apiKey.addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveKey();
});

async function saveKey() {
  const key = els.apiKey.value.trim();
  if (!key) {
    setStatus("请先粘贴 API Key。", "is-bad");
    return;
  }
  try {
    await api("/api/key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    els.apiKey.value = "";
    setKeyState(true);
    setStatus("密钥已保存。可以开始画了。", "is-ok");
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
}

els.undo.addEventListener("click", undo);
els.redo.addEventListener("click", redo);

document.getElementById("btn-clear").addEventListener("click", () => {
  resetInk();
  setStatus("笔迹已清空，从红色第一条指令开始。");
});

document.getElementById("btn-generate").addEventListener("click", generate);
document.getElementById("btn-generate-side").addEventListener("click", generate);
document.getElementById("btn-finish").addEventListener("click", finishCompose);
document.getElementById("btn-finish-side").addEventListener("click", finishCompose);
document.getElementById("btn-download").addEventListener("click", downloadLeft);
document.getElementById("btn-download-side").addEventListener("click", downloadLeft);
els.btnCompose.addEventListener("click", enterCompose);
els.btnSidebar.addEventListener("click", () => {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  relayout();
});
els.fab.addEventListener("click", () => {
  state.promptsOpen = !state.promptsOpen;
  if (!state.promptsOpen) {
    state.highlightGroup = null;
    document.querySelectorAll(".prompt-card").forEach((card) => card.classList.remove("is-hot"));
  }
  relayout();
});

document.querySelectorAll(".prompt-card textarea").forEach((box) => {
  box.addEventListener("focus", () => {
    state.highlightGroup = Number(box.dataset.group);
    document.querySelectorAll(".prompt-card").forEach((card) => {
      card.classList.toggle("is-hot", Number(card.dataset.group) === state.highlightGroup);
    });
    drawOverlay();
  });
  box.addEventListener("input", () => {
    if (state.highlightGroup === Number(box.dataset.group)) drawOverlay();
  });
  box.addEventListener("blur", () => {
    window.setTimeout(() => {
      const active = document.activeElement;
      if (active && active.matches && active.matches("textarea[data-group]")) return;
      state.highlightGroup = null;
      document.querySelectorAll(".prompt-card").forEach((card) => card.classList.remove("is-hot"));
      drawOverlay();
    }, 0);
  });
});

document.getElementById("btn-accept").addEventListener("click", async () => {
  try {
    await api("/api/accept", { method: "POST" });
    state.fromCompose = false;
    state.ui = "layout";
    state.promptsOpen = false;
    setTool("ellipse");
    resetInk();
    setStatus("已收下右边这一版。左边现在是新的当前稿。", "is-ok");
    relayout();
    await loadPdfs();
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
});

document.getElementById("btn-reject").addEventListener("click", async () => {
  try {
    await api("/api/reject", { method: "POST" });
    if (state.fromCompose) {
      state.ui = "ready";
      setStatus("已打回。画稿还在，可以改完再排。", "is-ok");
    } else {
      setStatus("已打回。笔迹还在，可以改完再排。", "is-ok");
    }
    relayout();
    await loadPdfs();
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
});

document.getElementById("btn-sample").addEventListener("click", async () => {
  try {
    await api("/api/sample", { method: "POST" });
    state.fromCompose = false;
    state.ui = "layout";
    state.promptsOpen = false;
    setTool("ellipse");
    resetInk();
    state.page = 1;
    setStatus("已加载示例文档。", "is-ok");
    relayout();
    await loadPdfs();
  } catch (err) {
    setStatus(err.message, "is-bad");
  }
});

els.file.addEventListener("change", async () => {
  const file = els.file.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    await api("/api/import", { method: "POST", body });
    state.fromCompose = false;
    state.ui = "layout";
    setTool("ellipse");
    resetInk();
    state.page = 1;
    setStatus(`已导入 ${file.name}`, "is-ok");
    relayout();
    await loadPdfs();
  } catch (err) {
    setStatus(err.message, "is-bad");
  } finally {
    els.file.value = "";
  }
});

document.getElementById("prev-page").addEventListener("click", () => goPage(-1));
document.getElementById("next-page").addEventListener("click", () => goPage(1));

[els.overlayLeft, els.overlayRight].forEach((overlay) => {
  overlay.addEventListener("pointerdown", startDraw);
  overlay.addEventListener("pointermove", moveDraw);
  overlay.addEventListener("pointerup", endDraw);
  overlay.addEventListener("pointercancel", endDraw);
  overlay.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    commitInstruction();
  });
  overlay.addEventListener("auxclick", (event) => {
    if (event.button === 1) event.preventDefault();
  });
});

els.scrollLeft.addEventListener("wheel", onCommitWheel, { passive: false });
els.scrollRight.addEventListener("wheel", onCommitWheel, { passive: false });

window.addEventListener("keydown", (event) => {
  if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA")) return;
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key === "z" && !event.shiftKey) {
    event.preventDefault();
    undo();
  } else if ((event.ctrlKey || event.metaKey) && (key === "y" || (key === "z" && event.shiftKey))) {
    event.preventDefault();
    redo();
  }
});

window.addEventListener("resize", () => {
  if (state.left.pdf) renderBoth();
});

syncBodyClass();
setStatus("正在打开文档…", "is-busy");
loadPdfs()
  .then(() => {
    updateChrome();
    setStatus("红色开始画第一条。画完后右键或 Ctrl+滚轮确认，换黄、再换蓝。侧栏「画版」可进入自由排版。");
  })
  .catch((err) => setStatus(err.message, "is-bad"));
