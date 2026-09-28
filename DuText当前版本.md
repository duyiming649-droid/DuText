# DuText 当前版本说明

> 由 Cursor Canvas 中的产品与架构讨论整理，并按 **2026-09 已实现代码** 校对。  
> 口号：**你来画，我来排版**。

---

## 1. 产品定位（仍然成立）

| 点 | 定论 |
| --- | --- |
| 承诺 | 你来画，我来排版 |
| 主界面 | 左右都是编译后的 PDF；笔迹只在蒙版上，不写进 `.tex` |
| 起点 | 已有可编译工程。原型导入 / 示例 `.tex`；PDF→LaTeX 还原仍未做 |
| 一次决策 | 整份「收下」或「打回」，不按段落合并 |
| AI 权限 | 只动排版。不改措辞、不删论点、不重写标题（layout 模式加粗除外） |
| 主入口 | 画布 +「排一版」。聊天框不是主控制 |
| 是否做 Agent | **不做**。生成是固定短流水线，不是开放 ReAct |

一句话：用户操作纸面，系统改 LaTeX，对照两版 PDF。生成是「看懂笔迹 → 改源码 → 编译」，然后停下来等人。

---

## 2. 和早期 Canvas 相比：已经落地的部分

这些在早期「还缺什么」里还是缺口，**当前代码已实现**：

| 早期缺口 | 当前状态 |
| --- | --- |
| 空闲 / 生成 / 待审 / 接受 / 打回 状态机 | 默认 layout 循环已通；画版另有 `compose → ready → result` |
| 接受拷什么、打回拷什么 | `accept`：right→left；`reject`：left→right（整工程目录） |
| 多页截哪一页 | 左右锁同一页；快照只拍当前页 |
| AI 允许改什么 | layout：强调加粗；compose：挪位 + 版面模板 |
| 喂给模型的包裹 | 截图 JPEG + 结构化笔画 / 意图 JSON + 全文 `.tex` + 可选备注 |
| 编译失败 | Pro 最多修 2 次（`REPAIR_TRIES`），仍失败则报错 |
| 导出 | `GET /api/export/left` 下载当前稿 PDF |
| 手势词汇（第一刀） | layout：椭圆 + `!` → 加粗；compose：矩形 / 箭头 / 黑笔 |
| 怎么触发生成 | 明确按钮「排一版」，不是实时重排 |
| 中文引擎 | 优先 `tools/tectonic.exe`，否则 xelatex / pdflatex |

**仍然刻意不做（与 Canvas 一致）：**

- PDF→LaTeX 还原、按段接受、右边当 Word 改、左边露源码、聊天主入口、简历/海报
- 开放 Agent / `create_react_agent`
- 把笔迹「转述成一段中文」再交给 Pro（中间必须是结构化意图）

---

## 3. 架构：双 PDF + 隐藏 LaTeX

```
左边 left/          右边 right/
  main.tex            main.tex
  main.pdf            main.pdf
  + 蒙版笔迹            （提案或空白画布）
```

- 版本单位：整个工程目录（`data/workspace/left|right`），不是单文件。
- 笔迹不进仓库；只服务这一次请求 / 这一轮画稿。
- 截图是给 Vision 看的证据（有损、按页）；真相在 `.tex`。
- Git 比喻：left ≈ HEAD，right ≈ 未合并提案；打回 = reset 右边；接受 = 右边合并成新左边。

本地服务：`127.0.0.1:8765`（`python -m dutext`）。

---

## 4. 模型流水线（DeepSeek，非 Agent）

| 步 | 谁 | 做什么 |
| --- | --- | --- |
| 1. perceive | `deepseek-v4-flash-vision-exp` | 看带笔迹的截图 → 结构化意图 JSON + 给人看的摘要 |
| 2. edit | `deepseek-v4-pro` | JSON + 全文 `.tex` → 新 TeX（layout 最小改；compose 可单页重排） |
| 3. compile | tectonic / xelatex / pdflatex | 编译 `right` |
| 4. repair | Pro，最多 2 次 | 日志回喂；仍失败则本次不出新页 |
| 5. wait | 界面 | 收下 / 打回 |

用户只粘贴 API Key（存 `data/deepseek_key.txt`，已 gitignore）。请求关闭 thinking，要求 JSON mode。

中间**禁止**只传一段中文转述；空间关系必须留在 JSON / 几何里。

---

## 5. 两种工作模式（当前版本）

### 5.1 Layout（默认）—「在现稿上画指令」

- 左边：当前稿 PDF + 笔迹蒙版  
- 右边：提案 PDF  
- 工具：椭圆、画笔  
- 指令：红 / 黄 / 蓝，一次最多 **3** 条  
- 确认一条：右键，或 **Ctrl+滚轮**；普通滚轮上下滚动  
- 当前支持的识别手势：圈选 + 感叹号 → `emphasize` → `\textbf{...}`  
- 「排一版」→ 截左边带笔迹页 → Vision → Pro → 编译右边  

状态循环：

| 状态 | 左边 | 右边 | 人做什么 |
| --- | --- | --- | --- |
| 空闲 | 当前稿 + 笔迹 | 与当前稿相同或旧提案 | 画，再点排一版 |
| 生成中 | 笔迹保留 | 等待 | 等 |
| 待审 | 旧稿 + 笔迹 | 新提案 | 收下或打回 |
| 收下 | 换成提案，笔迹清空 | 与左相同 | 继续画 |
| 打回 | 不动 | 用左边覆盖 | 改笔迹再排 |

### 5.2 Compose（侧栏「画版」）—「单页自由排版」

早期 Canvas 写过「不做空白画布」——那是相对「白板对成品」的产品否定。  
**当前版本有控制过的空白右页**：左原文 + 右空白，合成一张截图给 AI，只服务**单页**自由改版；多页文档的其他页不会被这轮直接改。

流程：

1. 侧栏点「画版」→ `compose`：左原文，右空白画布  
2. 画矩形 / 箭头 / 彩色笔 / 可选黑笔；右下角 AI 开四条备注  
3. 点「完成」→ `ready`：左边仍是画稿，回到可排一版界面  
4. 点「排一版」→ 左右拼图截图 + `mode=compose` → 出提案 → `result`  
5. 收下 / 打回（打回后画稿可保留在 ready）

工具含义：

| 工具 | 含义 |
| --- | --- |
| 矩形 | 左边：圈要挪的段落；右边：目标排版框（拖拽定大小，不手绘框） |
| 箭头 | 从左边指到右边同色目标框 |
| 画笔（彩） | 红黄蓝指令的补充笔迹，最多 3 条，右键 / Ctrl+滚轮确认换色 |
| 黑笔 | 第 4 条指令，可选。画版面实线 / 模板。按笔画位置尊重，只做拉直、均匀，不当成一整块装饰 |

右下角 AI 圆形按钮：

- 展开四条备注框（红 / 黄 / 蓝 / 黑），不盖住白纸：核心区让出右侧 dock  
- 在某一框打字时，对应笔迹荧光高亮  
- 备注与系统提示一起发给该条指令  

排版规则（place）：

- 文字尽量排进用户画的目标矩形  
- 用字号、行距去凑；原字号能放下就先不改字号  

导出：顶栏 / 侧栏「下载 PDF」= 下载左边当前稿。

---

## 6. API 一览（实现）

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/status` | 引擎、左右 PDF、rev、是否有 Key |
| POST | `/api/sample` | 加载示例并编译 |
| POST | `/api/import` | 上传 `.tex` |
| GET | `/api/pdf/{left\|right}` | 取编译 PDF |
| GET | `/api/export/left` | 下载左边 PDF（`dutext.pdf`） |
| POST | `/api/key` | 保存 DeepSeek Key |
| POST | `/api/generate` | `mode=layout\|compose`；截图 + strokes + notes |
| POST | `/api/accept` | right → left |
| POST | `/api/reject` | left → right |

意图种类（`Intent.kind`）：`emphasize` | `place` | `template`。  
笔画工具（`Stroke.tool`）：`pen` | `ellipse` | `rect` | `arrow` | `black`。

---

## 7. 前端 UI 结构（当前）

- 可折叠左侧栏：画版、下载当前稿  
- 核心双栏 + 中间收下 / 排一版 / 打回  
- 画版时：左右蒙版 + 跨栏箭头桥接层；右下角 AI FAB + 右侧四备注 dock  
- 状态 class：`is-compose` / `is-drawing` / `showing-result` / `prompts-open` / `sidebar-collapsed`

---

## 8. 工程目录（实现）

```
DuText/
  dutext/           # FastAPI + 静态页 + LLM / 编译 / 笔画管线
  samples/demo.tex
  tools/tectonic.exe
  data/workspace/{left,right}/
  data/deepseek_key.txt   # gitignore
  tests/
```

关键文件：`app.py`、`llm.py`、`pipeline.py`、`models.py`、`static/{index.html,app.js,app.css}`。

---

## 9. 早期 Canvas 主题索引 → 当前结论

| Canvas | 核心结论 | 与现版本 |
| --- | --- | --- |
| 该不该做 Agent | 产品不是 Agent；编译失败可有限重试 | 已按此实现 |
| 双 PDF + 隐藏 LaTeX | 左右都是 PDF，真相在 .tex | 已实现 |
| 左画右排 / 收下打回 | 整份接受或打回 | 已实现 |
| Vision → Pro | 结构化意图，禁止纯中文转述 | 已实现 |
| 目前最好的做法 | 固定短图 + 人最终决策 | 已实现；另加 compose |
| 现在还缺什么 | 状态机、导出、手势等 | 表见 §2；PDF 还原等仍缺 |
| PDF 导入最简案 | 还原后再进画画 | **未做**；仍从 `.tex` 起步 |

---

## 10. 下一刀仍可做（未实现）

- PDF→LaTeX 还原后进入画画  
- 更多 layout 手势（划掉、分组、旁写约束词等）  
- 真·工程目录（多文件、图、cls、bib）而不只是单 `main.tex`  
- Compose 与多页更稳妥的交互（目前明确只服务单页）  
- iPad / 触控优化  

---

*文档对应仓库实现快照：含 layout 三色指令加粗，以及 compose 画版（矩形+箭头+黑笔+四备注+下载+侧栏）。*
