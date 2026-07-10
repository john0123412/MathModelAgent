# MathModelAgent 启动说明

## 环境要求
- Docker Desktop
- Python 3.12 + uv
- Node.js + pnpm

> Agent 操作注意：Windows 本机前端 Node 工具链曾异常派生大量 `node.exe`，导致系统卡死。除非用户明确授权，agent 不应主动运行 `pnpm i`、`pnpm run build`、`vue-tsc`、`vite build`、`biome`、`npx biome` 或 `node_modules\.bin\*`。前端验证优先使用 Docker Compose 服务或由用户手动运行命令后回传结果。

---

## 方案一：Docker Compose（推荐）

### 启动

```powershell
cd D:\workspace\MathModelAgent
docker compose up --build -d   # 首次启动、改了依赖/Dockerfile 后，重建并后台运行
docker compose up -d           # 之后正常启动（有缓存）
docker compose ps              # 查看服务状态
```

### 停止

```powershell
docker compose down         # 停止并移除容器
docker compose stop         # 仅停止（保留容器）
docker compose down -v      # 停止并删除数据卷（⚠️ 清空 Redis 数据）
```

启动后访问 http://localhost:5173

### 启动后检查

```powershell
curl.exe http://127.0.0.1:5173/
curl.exe http://127.0.0.1:5173/api/docs
docker compose logs backend --tail=200
```

Docker 前端通过 Vite dev server 代理访问后端：浏览器请求
`http://localhost:5173/api/*` 会被转发到 Compose 内部的 `backend:8000`，
WebSocket 请求 `ws://localhost:5173/ws/task/<task_id>` 会被转发到后端
`/task/<task_id>`。如果 Docker Desktop 能正常发布后端端口，也可以直接访问
`http://127.0.0.1:8000/docs`；若宿主机端口发布异常，以 `5173/api/docs`
作为 Docker 验证入口。

后端 Docker 内验证：

```powershell
docker compose exec backend uv run python -m unittest app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
docker compose exec backend uv run python -m ruff check app
```

> 不要持续 `docker compose logs -f`。排查时默认 `--tail=200`，最多临时扩大到 `--tail=2000`。

### 前置条件
- `backend/.env.dev` 已配置好 API Key
- Docker Desktop 正在运行

WebUI 侧边栏的 API Key 配置会通过 `/save-api-config` 应用到当前后端进程，
接口响应会标记 `scope=runtime`、`persisted=false`。它不会写回
`backend/.env.dev`；后端或容器重启后仍以 `.env.dev` 或系统环境变量为准。
注意：前端 Pinia store 仍会在浏览器本地持久化用户填写的 API key；这里的
`persisted=false` 只表示后端没有把配置写入服务器文件。

### 构建说明

后端镜像在 Python 基础镜像内通过带超时和重试的 `pip install uv==0.11.14`
安装 uv，不再从 `ghcr.io/astral-sh/uv:latest` 复制二进制文件。这样可以避免
网络不稳定时 GHCR token/metadata 获取失败导致 Docker 构建在依赖同步前中断，
也降低 PyPI 下载 uv 大 wheel 中途 read timeout 的概率。

### 架构
- **backend**（:8000）→ 支持 checkpoint/resume
- **frontend**（:5173）→ 通过 `/api` 和 `/ws` 代理连接 Compose 内部 backend:8000
- **redis**（内部网络）

### Restart 策略
所有容器配置了 `restart: unless-stopped`：
- Docker Desktop 重启 → 容器自动恢复
- 系统重启 → 容器自动恢复
- 手动 `docker stop` → 不会自动恢复

---

## 方案二：本地开发

### 一键启动
```
D:\workspace\MathModelAgent\win_start.bat
```

### 手动启动

> 本地开发流程需要前端 Node 工具链。agent 默认不主动执行以下前端命令；如果需要，请由用户手动运行或明确授权。

**1. 启动 Redis**
```
docker start redis-mma
```

**2. 启动后端（新终端）**
```
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\activate
set ENV=dev
set REDIS_URL=redis://127.0.0.1:6379/0
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

**3. 启动前端（另一个新终端）**
```
cd D:\workspace\MathModelAgent\frontend
pnpm run dev
```

**4. 打开浏览器** 访问 http://localhost:5173

---

## 端口说明

| 服务 | Docker Compose | 本地开发 |
|------|----------------|----------|
| Frontend | 5173 | 5173 |
| Backend | 内部 8000；前端代理入口 5173/api；宿主直连 8000 取决于 Docker Desktop 端口发布状态 | 8003 |
| Redis | 内部网络 | 6379 |

---

## 功能说明

### 下载任务工作区文件

文件面板支持单文件下载和“下载全部”。后端 `GET /download_all_url?task_id=...`
会在对应任务目录内按需生成 `all.zip`，然后返回 `/static/<task_id>/all.zip`
下载链接。压缩包会排除已有 `all.zip`、临时文件和常见缓存目录，并限制单文件和
总打包大小，避免意外打包过大的工作目录。

### 无外部数据题目的 EDA 边界

当任务工作目录没有 `.csv` / `.xlsx` 等外部数据集时，代码手不应为了 EDA 随机生成样本
或创建“模拟数据集.csv”。这类题目只做题目给定参数表、单位一致性、约束可行性、
边界点或可行域核验；只有确实存在外部数据集时，才执行缺失值、异常值、分布可视化等
数据驱动 EDA。

### 断点续传（Checkpoint/Resume）

**原理**：
1. 任务在每个阶段（eda/ques1/ques2...）完成后自动保存检查点到 `checkpoint.json`
2. 中断后重启，通过 `GET /tasks` 检测到 `status: "interrupted"`
3. 点击"继续任务"，调用 `POST /modeling/{task_id}/resume`
4. 系统从检查点恢复，优先加载变量快照；如快照不可用，再执行 notebook 重放

**重建计算环境机制**：
- 优先读取 `variable_snapshot.pkl`，秒级恢复内核变量
- 读取 `variable_snapshot_meta.json`，判断快照对应的 notebook 位置
- 快照成功时，只增量重放快照之后新增的代码单元格
- 快照不可用时，回退到 notebook 全量重放
- 续传重放使用 `replay_code()`，只执行代码，不写入 notebook，不向前端重复推送代码单元格
- 重建完成后继续执行未完成阶段

### 实时消息干预

**原理**：
1. WebSocket 双向通信：前端发送 → 后端接收 → 推入队列
2. Agent 在每次 LLM 调用前检查队列
3. 用户消息作为额外上下文注入到 `chat_history`
4. 前端实时回显用户输入

### Token 用量统计

每次 LLM 成功调用后，后端会在任务目录写入 `token_usage.json`，只保存按 agent
聚合的 `chat_count`、`prompt_tokens`、`completion_tokens`、`total_tokens`
和模型名，不保存 prompt、completion、tool args、API key 或 base_url。
可通过以下接口读取：

```powershell
curl.exe "http://127.0.0.1:8000/track?task_id=<task_id>"
```

该统计用于运行过程观察和粗略成本估算，不等同于模型供应商账单。
统计写入是 best-effort：写入失败不会触发 LLM 请求重试，也不会阻断任务继续运行。
当前只保证单进程内加锁累加；如果后续部署为多 worker/多进程，该文件不应作为强一致
成本账单依据。

### 导出模板选项（Export Profile）

新建建模任务默认使用 `cumcm2026`，匹配当前高教社杯/国赛交付口径。历史兼容的
`default` profile 仍保留；只有显式传 `export_profile=default` 时才会走旧默认排版。

**可选值**：
- `default`（兼容）：保持原有 Markdown/DOCX/PDF/LaTeX sidecar 导出行为
- `cumcm2025`：套用 2025 年高教社杯/国赛（CUMCM）格式规范
- `cumcm2026`：套用 2026 年高教社杯/国赛（CUMCM）格式修订稿；PDF 不生成目录，也不启用 pandoc 自动章节编号，避免与 Markdown 模板中的 `一、`、`1.1` 手写编号叠加
- `huashubei`：华数杯模板，仅用于华数杯任务；参加高教社杯/国赛时请使用 `cumcm2026`

**如何选择**：前端提交页已经暴露“排版”选择，默认使用 `cumcm2026`；后端
`POST /modeling` 表单字段漏传 `export_profile` 时也默认使用 `cumcm2026`。脚本、
curl 或旧客户端仍建议显式传入，便于审计：

```powershell
curl.exe -X POST http://127.0.0.1:8000/modeling `
  -F "ques_all=..." `
  -F "comp_template=CHINA" `
  -F "format_output=Markdown" `
  -F "export_profile=cumcm2026"
```

> 高教社杯/国赛任务应保持 `cumcm2026`；`huashubei` 仅保留为华数杯兼容 profile，不作为本次赛事默认选项。

**`cumcm2025` 相对 `default` 的差异**：
1. **PDF**：在默认排版变量基础上追加 `--toc`（生成目录）、`--number-sections`（章节自动编号），页边距调整为 `top=3cm,bottom=2.5cm`（默认为 `top=2.6cm,bottom=2.6cm`）
2. **LaTeX sidecar**：使用 `gmcmthesis` 模板（`zh/cumcm2025-gmcmthesis`）而非默认的 `ctexart`，并复制模板资源（`gmcmthesis.cls`、封面图 `figures/logo2025.png`、`figures/title2025.pdf`）到生成的 `latex_project/` 目录
3. **DOCX**：套用 `format2025_reference.docx` 作为 pandoc `--reference-doc`，页面样式（页边距 2.5cm、正文字体 Times New Roman / 宋体 10.5pt）来自 2025 年 CUMCM 官方论文格式规范（`format2025.doc`，用 LibreOffice 转换为 `.docx` 后仅取其 Word 样式，不含原文内容）

**`cumcm2026` 相对 `cumcm2025` 的差异**：
1. **PDF**：不生成目录，也不使用 `--number-sections`。当前 Markdown 模板已经带有 `一、`、`1.1` 等手写编号，关闭 pandoc 自动编号可以避免导出后出现 `2 一、问题重述`、`2.1 1.1 问题背景` 之类的重复编号。
   PDF 导出会在摘要/关键词后做 PDF-only 分页，支持裸 `关键词：...` 和加粗内联
   `**关键词**：...`，保证摘要页独占第一页、正文从第二页开始；该分页不写回
   `res.md`，也不影响 DOCX 或 LaTeX sidecar。
   PDF-only 预处理还会给连续中文长句插入内部断行标记，由 Lua filter 转为 LaTeX 断点，避免 Pandoc/XeLaTeX 在特定中文段落上生成超出页边距的不可断长行。
   主 PDF 页边距为 `left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm`。底边距大于规范最低 2.5cm，是为了给实际字体字形 bbox 留出安全余量，避免正文末行侵入 CUMCM 2.5cm 内容边距保护区。
2. **LaTeX sidecar**：沿用 gmcmthesis 资源目录，但模板键为 `zh/cumcm2026-gmcmthesis`，电子版从摘要页开始；`latex_project/main.tex` 默认输入结构化 `sections/*.tex`，同时保留 `sections/imported_body.tex` 作为兼容审计文件。

> 当前若目标赛事是高教社杯全国大学生数学建模竞赛，应优先使用 `export_profile=cumcm2026`；不要使用 `huashubei`，后者是华数杯 profile。

### CUMCM 2026 模板状态与替换入口

`cumcm2026` 当前是基于官方 2026 修订稿规范实现的暂定模板，不是官方最终
DOCX/LaTeX 模板包。当前暂时复用 2025 DOCX reference 和 2025 `gmcmthesis`
LaTeX 资源；2026 正式 DOCX/LaTeX 模板发布后，按
`docs/md/CUMCM2026模板替换指南.md` 替换。

官方 2026 论文格式规范页面：
`https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html`。
当前自动化流程按其中的电子版口径执行：参赛论文电子版是单独 PDF/Word 文件
（建议 PDF，大小不超过 20MB），不要放承诺书和编号专用页，第一页必须为摘要页；
支撑材料另行压缩提交，至少包含所有可运行源程序、数据资料和较大篇幅中间结果图表。

**已知限制**：
- `cumcm2026` 当前复用 2025 年 `gmcmthesis` 模板资源目录和 `format2025_reference.docx`
  的 Word 样式作为修订稿口径实现；2026 正式模板文件发布后，需要重新复核并替换
  LaTeX 模板与 DOCX reference-doc。
- LaTeX sidecar 编译产物（`latex_project/`）属于候选导出，提交前仍需人工核对（`candidate_manifest.json` 中会标注 `known_risks`）。主交付链路是 `res.md`、`res.docx`、`res.pdf` 和 `res.json`。
- PDF 视觉检查是低成本后验检查，会覆盖 A4、非空、文本可提取、20MB 文件大小、
  摘要首页、无目录、正文 30 页以内、物理边缘越界和 CUMCM 2.5cm 内容边距风险；
  还会阻断 `承诺书`、`编号专用页`、`参赛队号` 等身份/封面字段；不能替代人工排版
  验收。正式提交前仍需人工翻看摘要页、公式密集页、宽表、附录源码、参考文献和最后几页。
- 主 PDF 导出显式关闭 pandoc raw TeX，避免源码中的 LaTeX 模板字符串泄漏成正文命令。正文应优先使用 Markdown 表格和标准 `$...$`、`\(...\)` 数学公式，不要依赖 `\begin{table}`、`\begin{align}` 等 raw LaTeX 环境。
- 论文附录会自动重建：附录A列出支撑材料，附录B只保留核心建模/求解/作图代码摘录；
  完整可运行 notebook/脚本保留在支撑材料中。这样既满足电子版论文单文件、20MB、
  正文页数和可读性门禁，又能通过 `candidate_manifest.json` 与
  `submission_audit_report.json` 追踪完整源程序。后处理会删除附录中的批量
  `print(...)`/`printf`/`console.log` 控制台输出语句，并通过
  `paper_preflight_report.json -> checks.appendix_console_noise` 阻断 print-heavy
  正式 PDF。
- `paper_preflight_report.json` 是规则/正则驱动的格式与证据链门禁，不证明模型、求解和论证一定正确；`PASS` 后仍需人工复核数学内容。
- 对无外部数据集的确定性参数题，后处理会清理正文/支撑材料中的 Monte Carlo、蒙特卡洛、随机模拟等探索性随机模拟内容，将样本数据 EDA 用语规范为参数核验，并删除可能触发 Pandoc definition-list 误解析的孤立 `: ... DOI ...` 参考行。
- **字体**：PDF/LaTeX sidecar 优先使用官方格式规定的 Times New Roman/SimSun 等正式字体；精简版 Docker 镜像默认不含这些 Windows/Office 专有字体，会在编译期自动检测（`fc-match` / fontspec `\IfFontExistsTF`）并回退到免费等效字体，不影响能否编译成功，但正式提交前建议人工核对排版观感是否符合要求。两类字体的 fallback 途径不同：
  - **英文/Latin 字体**（Times New Roman → Liberation Serif、Courier New → Liberation Mono、Arial → Liberation Sans）：可通过构建时开启 `INSTALL_MS_FONTS=true` 装真正的 Microsoft Core Fonts（`ttf-mscorefonts-installer`），从而不必 fallback：
    ```bash
    docker compose build --build-arg INSTALL_MS_FONTS=true backend
    ```
    该选项默认关闭，因为它需要接受 Microsoft 的字体许可协议（EULA）并在构建时从外部镜像下载字体二进制文件，不适合作为默认公开镜像行为，仅建议在你自己私有构建、且已知晓并接受该许可与网络依赖时开启。
  - **中文字体**（SimSun/SimHei/KaiTi/STXinwei/LiSu）：**`INSTALL_MS_FONTS` 对此无效**——`ttf-mscorefonts-installer` 只包含 Times New Roman/Arial/Courier New 等英文字体，不含任何中文 Windows 字体。这些中文字体本身没有可合法分发的开源渠道（不像 Liberation 之于 Times New Roman那样有官方免费克隆），因此容器内始终 fallback 到 `fonts-noto-cjk`/`texlive-lang-chinese` 提供的 Noto Serif/Sans CJK SC、AR PL KaitiM GB，没有"装包补全"的选项。如需真正的 SimSun/SimHei/KaiTi 排版效果，只能在已合法安装这些字体的宿主机（如 Windows 本地开发环境）上编译，或自行挂载你合法持有的字体文件到容器内。

**Docker 使用宿主机正式字体（推荐自动化方案）**：

Docker 不能把开源字体“转换”为 Times New Roman/SimSun 这类专有字体；正确做法是
只读挂载你本机已经合法安装的字体目录。Compose 已内置可选挂载点，Windows 上在仓库根目录
创建或编辑 `.env`：

```env
MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts
```

然后重建/重启后端：

```powershell
docker compose up --build -d backend
docker compose exec backend fc-match "SimSun"
docker compose exec backend fc-match "Times New Roman"
```

后端入口会自动对挂载目录运行 `fc-cache`。若 `fc-match` 命中 `SimSun`/
`Times New Roman`，后续 Docker PDF 会优先使用这些正式字体；未设置该变量时，
默认挂载 `backend/fonts`，仍按可用字体自动 fallback。

### 人工建模确认门禁

默认关闭，不影响全自动流程：

```env
HUMAN_MODEL_GATE_ENABLED=false
```

开启后，建模手完成后会先写出：

- `modeler_plan.json`
- `modeler_plan.md`
- `modeling_decision.json`
- `modeling_decision.md`
- `checkpoint.json`

任务状态会变为 `waiting_review`，不会进入 Coder。人工确认建模方案后调用：

```powershell
curl.exe -X POST http://127.0.0.1:8000/modeling/<task_id>/approve-modeling `
  -H "Content-Type: application/json" `
  -d "{\"comment\":\"建模方案确认通过\"}"
```

确认接口会把 `modeling_decision.json` 标记为 `approved`，再复用现有 checkpoint/resume 链路从 Coder 阶段继续执行，不会重跑 Coordinator 或 Modeler。

### LLM 请求超时

OpenAI-compatible、Responses 和 Anthropic provider 会使用
`LLM_REQUEST_TIMEOUT_SECONDS` 控制单次请求超时，默认 `90` 秒。部分兼容端点或较慢模型
在建模手/写作手阶段响应时间可能超过 SDK 默认值；如连续出现 `Request timed out`，
可在 `backend/.env.dev` 中临时调大该值后重启后端。

### 结构化 LaTeX Sidecar

LaTeX sidecar 现在生成两类正文文件：

- `latex_project/sections/imported_body.tex`：完整 Markdown 一次性转换的兼容文件，便于对照和回退。
- `latex_project/sections/00_*.tex`、`01_*.tex` 等：按 Markdown 顶层标题拆分后的结构化章节文件。

生成前会对 LaTeX sidecar 专用 Markdown 做轻量兼容处理：保留已有 fenced code block，
对未 fenced 的 `# Cell n` notebook 片段补代码围栏，并在章节拆分时忽略代码块内的
`#` 注释，避免附录源码被误拆成正文章节。模板外壳同时兼容新版 Pandoc 生成的
`\pandocbounded`、`\passthrough` 图片/inline 片段，并把图片搜索路径设为
`./`、`../`、`sections/`、`figures/`，以便引用任务目录根部图片。

导出器会扫描 Markdown 和生成的 LaTeX 中引用的本地图片，把存在的图片复制到
`latex_project/` 和 `latex_project/figures/`，并把缺失引用写入
`tex_export_status.json -> missing_assets`。这样候选 LaTeX 工程脱离任务根目录后也
能尽量独立编译；如果图片确实不存在，主交付链路不受影响，但 sidecar 风险会被记录。
若原始图片文件名包含 `%`、中文、`±` 等 LaTeX 高风险字符，sidecar 会复制为
`figures/figure_XX.ext` 安全文件名并重写 `sections/*.tex` 的
`\includegraphics` 引用；这只影响 `latex_project/`，不改 `res.md`、主 PDF 或 DOCX。

`latex_project/main.tex` 默认输入结构化章节文件，`tex_export_status.json` 会记录：

- `structured_sections`
- `structured_section_count`
- `main_uses_structured_sections`
- `copied_assets`
- `missing_assets`
- `compile_attempted`
- `compile_success`
- `compile_reason`
- `compile_failure_summary`

如果 Markdown 没有可拆分的顶层标题，sidecar 会回退到输入 `sections/imported_body.tex`。
如果 `latexmk` 可用但编译失败，导出器会 fallback 到连续两次 `xelatex`。sidecar
编译失败只写入 `tex_export_status.json`，不会让主交付链路失败。
  - Windows 本地导出可以直接使用系统自带的正式字体，不受 Docker 镜像限制，见下一节。

---

## Windows 本地 PDF 导出 / 手动编译

Docker 容器里的 PDF/LaTeX 导出面向**自动化预览**：字体缺失时会静默回退到开源等效字体（见上一节），保证批量任务稳定跑通，但排版观感和官方格式规范会有细微差异。Windows 本机通常已经自带 Times New Roman、SimSun、SimHei、KaiTi 等正式字体（`C:\Windows\Fonts`），直接在本机跑一遍导出，可以拿到更接近国赛/论文正式格式的 PDF。

**什么时候应该用 Windows 本地导出**：
- 正式提交前，想用真实的 Times New Roman/SimSun/KaiTi 排版效果复核一遍
- Docker 里因为缺依赖（pandoc/xelatex 未装全，或缺某个 `.sty` 包）导致 PDF/LaTeX sidecar 编译失败或被跳过，本机已经装好完整 TeX 发行版可以绕过这个问题
- 需要临时用非默认字体（比如给某个变体格式用不同字体）快速试一版，不想改 Docker 镜像

**依赖安装**：
1. **Pandoc**：https://pandoc.org/installing.html
2. **XeLaTeX**：装 MiKTeX（https://miktex.org/download，体积小、按需自动装包）或 TeX Live（https://tug.org/texlive/，体积大但一次装全，推荐已知会用到 `texlive-lang-chinese`/`ulem`/`lmodern` 等包的情况）
3. **Python 环境**：项目已有的 `backend/.venv`（`uv sync` 装好的那个），不需要额外装

**检查依赖是否可用**（在 `backend/` 目录下）：

```powershell
pandoc --version
xelatex --version
python --version

# 或者用项目自带的 check 子命令，会额外检测 Times New Roman/SimSun/SimHei/KaiTi/Arial/Courier New 是否已安装
uv run python -m app.tools.export_cli check
```

**方式一：直接导出 PDF**（最快，内部还是走 pandoc + xelatex）：

```powershell
cd backend
uv run python -m app.tools.export_cli pdf --input path\to\res.md --output path\to\res.pdf --profile cumcm2025 --local --update-status
```

- `--local` 是关键参数：不加它会走跟 Docker 一样的策略（也能跑，但检测到 Times New Roman 缺失时不会给你打印本机安装状态提示，只写日志）；加了以后会明确报告每个字体是否命中本机已安装的版本，并且——只要你没有用下面的 `--mainfont` 等参数手动指定——官方字体检测到确实已经装了才会使用，检测不到就按开源字体回退并打印原因，不会不声不响换成别的字体。
- `--update-status` 会在 PDF 重导成功后刷新 `export_status.json`、`pdf_visual_check.json`
  和 `submission_audit_report.json`；若 `candidate_manifest.json` 已存在，也会同步刷新，
  避免正式字体重导后审核报告仍引用旧的 Docker fallback 记录。
- `--profile` 可选 `default` / `cumcm2025` / `cumcm2026` / `huashubei`，与 Docker 端行为一致。高教社杯/国赛建议用 `cumcm2026`。

仓库内提供了一个最小样例，可直接用来检查 Windows 本地导出链路：

```powershell
cd backend
uv run python -m app.tools.export_cli check
uv run python -m app.tools.export_cli pdf --input examples\pdf_export_sample\res.md --output examples\pdf_export_sample\res.pdf --profile cumcm2025 --local --font-config examples\pdf_export_sample\fonts.json
uv run python -m app.tools.export_cli latex --input examples\pdf_export_sample\res.md --work-dir examples\pdf_export_sample --profile cumcm2025
```

**方式二：导出 LaTeX sidecar 项目后手动编译**（更稳，能看到完整编译日志，也能自己再精修排版）：

```powershell
cd backend
uv run python -m app.tools.export_cli latex --input path\to\res.md --work-dir path\to\workdir --profile cumcm2025
```

导出后会在 `path\to\workdir\latex_project\` 下生成 `main.tex` 等文件；如果本机 `latexmk`/`xelatex` 在 PATH 里，命令会自动尝试编译并直接告诉你是否成功。自动编译优先尝试 `latexmk -xelatex`，失败后 fallback 到连续两次 `xelatex`；如果仍失败，`tex_export_status.json` 会记录 `compile_reason`、`compile_failure_summary` 和日志尾部。想手动复现时，进入该目录执行：

```powershell
cd path\to\workdir\latex_project
xelatex -interaction=nonstopmode main.tex
xelatex -interaction=nonstopmode main.tex
```

跑两遍是为了让目录（`\tableofcontents`）和交叉引用正确生成。当前 `default`/`cumcm2025` 两个模板都没有用 `bibtex`/`biber`（没有独立的 `.bib` 参考文献库，参考文献是手写在正文里的 `thebibliography` 环境），所以不需要额外的 `bibtex main` / `biber main` 步骤；如果你自己往模板里加了 `.bib` 文件，编译顺序需要改成：

```powershell
xelatex -interaction=nonstopmode main.tex
bibtex main          # 或者 biber main，取决于用 bibtex 还是 biblatex
xelatex -interaction=nonstopmode main.tex
xelatex -interaction=nonstopmode main.tex
```

**手动指定字体**：不想用 profile 默认的字体名，或者本机装的是变体名称（比如公司电脑上中文字体被替换过），可以显式覆盖，用户指定的值总是优先且不会被静默替换：

```powershell
uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --profile cumcm2025 --local `
  --mainfont "Times New Roman" --cjk-mainfont "SimSun" --cjk-sansfont "SimHei" --cjk-monofont "KaiTi"
```

或者写一个 JSON 配置文件复用（字段名对应 pandoc/fontspec 变量名）：

```json
{
  "mainfont": "Times New Roman",
  "CJKmainfont": "SimSun",
  "CJKsansfont": "SimHei",
  "CJKmonofont": "KaiTi"
}
```

```powershell
uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --profile cumcm2025 --local --font-config fonts.json
```

如果指定的字体本机检测不到已安装，CLI 会在终端打印明确提示（而不是静默换成别的字体或直接失败），例如：

```
[字体提示] 你指定的字体 'Times New Roman'（mainfont）在本机未检测到已安装，仍会按你的设置使用；如编译报字体找不到，请检查拼写或先安装该字体。
```

**Docker fallback PDF 与 Windows 本地 PDF 的区别**：

| | Docker/Linux 自动化路径 | Windows 本地（`--local`） |
|---|---|---|
| 字体检测方式 | `fc-match`（fontconfig） | 注册表（`HKEY_LOCAL_MACHINE`/`HKEY_CURRENT_USER` 的 Fonts 项） |
| 官方字体已安装时 | 直接使用 | 直接使用 |
| 官方字体缺失时 | 静默 fallback 到 Liberation/Noto CJK/AR PL KaitiM GB，只写日志 | fallback 到同一套开源字体，但会把提示打印到终端 |
| 用户可否覆盖字体 | 可以（`font_overrides` 参数），但主要面向程序调用 | 可以（`--mainfont` 等 CLI 参数/`--font-config`），面向交互式使用 |
| 定位 | 批量自动化预览，保证能编译 | 正式提交前用真实系统字体复核排版 |

> **明确建议**：Docker 默认 fallback 生成的 `res.pdf`/`latex_project/main.pdf` 只用于自动化预览，不代表最终排版效果；正式提交前，建议用上面的 Windows 本地流程，在已安装 Times New Roman/SimSun/SimHei/KaiTi 等正式字体的机器上重新编译一次 PDF，并人工检查版式、页边距、字号是否符合官方格式规范。

## 标准化最终交付流程

对已完成任务推荐按以下顺序刷新最终交付物：

```powershell
cd D:\workspace\MathModelAgent
docker compose up -d backend
docker compose exec backend fc-match "SimSun"
docker compose exec backend fc-match "Times New Roman"

docker compose exec backend uv run python -c "from app.tools.paper_postprocessor import prepare_paper_markdown; from app.utils.common_utils import md_2_docx; report=prepare_paper_markdown('/app/project/work_dir/<task_id>', export_profile='cumcm2026', declared_problem_count=<题目正式问题数>); print(report['status']); md_2_docx('<task_id>', export_profile='cumcm2026')"

docker compose exec backend uv run python -m app.tools.export_cli pdf --input project/work_dir/<task_id>/res.md --output project/work_dir/<task_id>/res.pdf --profile cumcm2026 --update-status

docker compose exec backend uv run python -m app.tools.submission_audit --work-dir project/work_dir/<task_id> --require-official-fonts
```

验收要点：

- `paper_preflight_report.json = PASS`，且 `checks.appendix_console_noise.passed=true`。
- 若 `paper_preflight_report.json = CONDITIONAL_PASS`，`submission_audit_report.json`
  会降级为 `WARN`，表示主交付已生成但仍有条件项需要人工接受或修正；正式提交前优先修到
  `PASS`。
- `pdf_visual_check.json = PASS`。
- `submission_audit_report.json = PASS`（严格字体门禁）。
- PDF 文本中不应出现 `print(`、`printf`、`console.log` 等批量控制台输出。
- `candidate_manifest.json` 登记 `notebook.ipynb`、图片、数据文件等支撑材料。

### 自动提交审核门禁

任务完成时会自动生成：

- `submission_audit_report.json`
- `submission_audit_report.md`

该报告汇总主交付文件、`paper_preflight_report.json`、`pdf_visual_check.json`
和 `export_status.json -> pdf.font_resolution`。默认自动流程中，如果 PDF 使用
Docker fallback 字体，报告为 `WARN` 而不是阻断任务；如果
`paper_preflight_report.json = CONDITIONAL_PASS`，报告同样为 `WARN`，需要人工查看
具体条件项后决定修正或接受。正式提交前可以启用严格字体门禁：

```powershell
cd backend
uv run python -m app.tools.submission_audit --work-dir project\work_dir\<task_id> --require-official-fonts
```

严格模式下，只要 PDF 仍使用 Liberation/Noto/AR PL 等 fallback 或字体来源未知，
报告就是 `FAIL` 并返回非零退出码。解决方式是先按上文挂载
`MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 后在 Docker 重导，或在 Windows 本机用
`export_cli pdf --local --update-status` 重导，再重新运行审核命令。

**如果本机缺少 Pandoc 或 XeLaTeX**：`export_cli` 的 `check`/`pdf`/`latex` 子命令都会在真正调用前先检测，缺失时打印类似下面的信息并以非零退出码结束，不会跑到一半才报错：

```
[错误] 未检测到 pandoc，请先安装并用 `pandoc --version` 确认可用。
[错误] 未检测到 xelatex，请先安装 MiKTeX 或 TeX Live 并用 `xelatex --version` 确认可用。
```

---

## 功能测试

### 测试 0：轻量真实案例

适合 Docker 重建后做端到端验收：

```text
某工厂生产 A、B 两种产品。
A 需要 2 小时机器时间、1 小时人工时间，利润 40 元；
B 需要 1 小时机器时间、2 小时人工时间，利润 30 元；
机器时间最多 100 小时，人工时间最多 80 小时。
求最优生产方案，并分析机器时间增加 10 小时时利润变化。
```

验收标准：

- `GET /tasks` 中任务状态为 `completed`
- 工作目录生成 `res.md`、`res.json`、`res.docx`、`res.pdf`、`candidate_manifest.json`
- `paper_preflight_report.json = PASS`；若为 `CONDITIONAL_PASS`，需人工确认条件项，
  `submission_audit_report.json` 会是 `WARN`
- `export_status.json -> pdf.success = true`
- `pdf_visual_check.json = PASS`
- `pdf_visual_check.json -> checks.abstract_first_page/body_page_limit/content_margin/no_table_of_contents/submission_anonymity`
  均应通过
- `tex_export_status.json -> compile_success = true`
- `latex_project/main.pdf` 存在且非空
- `paper_preflight_report.json -> checks.references.missing_inline = []`
- `paper_preflight_report.json -> checks.tables.uncaptioned_tables = []`
- `paper_preflight_report.json -> checks.extra_problem_labels.issues = []`
- 续传相关测试应生成 `checkpoint.json`、`variable_snapshot.pkl`、`variable_snapshot_meta.json`
- 后端日志出现 `变量快照已恢复` 或 `快照后增量重放`
- 如果容器环境异常导致 `pandoc`/`xelatex` 不可用，`res.pdf` 和 LaTeX sidecar 可能被跳过；只要 Markdown/Word/JSON 成功，不视为主流程失败，但正式提交前必须补导出 PDF 并复核。

### 测试 A：断点续传

1. 打开 http://localhost:5173
2. 提交一个任务（选择"使用该案例"）
3. 等待任务运行（观察聊天区出现代码执行日志）
4. 模拟崩溃：停止后端
   ```powershell
   docker compose stop backend
   ```
5. 重启后端
   ```powershell
   docker compose up -d
   ```
6. 刷新浏览器，任务应显示 `interrupted` 状态
7. 点击"继续任务"按钮
8. 观察进度消息和最终产物

### 测试 B：实时消息干预

1. 提交一个任务
2. 等待 CoderAgent 开始运行（聊天区出现代码执行日志）
3. 在输入框发送干预消息：
   ```
   请在代码中添加更详细的注释，并输出中间变量的值
   ```
4. 观察：
   - 前端回显消息
   - 后端日志显示收到用户输入
   - Agent 行为是否有变化

### 测试 C：cumcm2026 高教社杯/国赛导出模板

前端排版选项默认就是 `cumcm2026`；也可以用 curl 直接提交（参考"导出模板选项"一节）：

```powershell
curl.exe -X POST http://127.0.0.1:8000/modeling `
  -F "ques_all=某工厂生产 A、B 两种产品……（同测试 0 案例）" `
  -F "comp_template=CHINA" `
  -F "format_output=Markdown" `
  -F "export_profile=cumcm2026"
```

验收标准：
- 任务正常完成，`res.md`/`res.docx`/`res.pdf`（如已装 pandoc）正常生成
- `export_status.json` 中 `export_profile` 应为 `cumcm2026`，PDF 命令不应包含 `--toc` 或 `--number-sections`
- `paper_preflight_report.json` 应包含 `status`/`conclusion`、`export_profile`、`claim_trace` 等检查项
- 如果本机装了 pandoc + latexmk/xelatex，`latex_project/main.tex` 应包含 `CUMCM 2026 LaTeX sidecar`，且 `latex_project/gmcmthesis.cls`、`latex_project/figures/logo2025.png` 等模板资源已被复制；正文引用的本地图片应出现在 `tex_export_status.json -> copied_assets`，不存在的图片会出现在 `missing_assets`；含 LaTeX 高风险字符的图片名允许以 `figures/figure_XX.ext` 安全副本形式出现
- 换回 `export_profile=default`（或不传该字段）重新提交一次，确认输出与之前完全一致（回归验证）

---

## 常见问题

### OPENALEX_EMAIL 未配置
`OPENALEX_EMAIL` 未配置时，系统会跳过 OpenAlex，但文献搜索不会整体失效，仍会使用 Semantic Scholar / Crossref / arXiv。

如需启用 OpenAlex，编辑 `backend/.env.dev` 添加:
```
OPENALEX_EMAIL=你的邮箱
```
重启后端生效。

### Tavily 网页搜索如何启用
Tavily 用于补充网页、官方报告和数据来源，不替代学术数据库。编辑 `backend/.env.dev`：
```
TAVILY_API_KEY=你的TavilyKey
SEARCH_ENABLED=true
```

启用后，Writer 的 `search_papers` 工具可以在需要背景资料时包含 Tavily 网页结果。若工具指定 `source_types=["web"]`，系统只请求 Tavily，不请求学术文献源。

### 文献搜索来源
`search_papers` 当前会聚合：

- OpenAlex：配置 `OPENALEX_EMAIL` 后启用
- Semantic Scholar：默认启用，可能对匿名请求限流
- Crossref：默认启用，用于 DOI 和出版信息补全
- arXiv：默认启用，用于数学、统计、优化、计算机方向预印本
- Tavily：配置 `TAVILY_API_KEY` 且 `SEARCH_ENABLED=true` 后启用，用于网页资料补充

### Redis 连接失败
```powershell
# 本地开发
docker start redis-mma

# Docker Compose
docker compose logs redis --tail=200
```

### 端口被占用
```powershell
netstat -ano | findstr ":8000"
netstat -ano | findstr ":5173"
taskkill /PID <PID> /F
```

### 任务状态不显示 "interrupted"
检查 checkpoint.json 是否存在：
```powershell
ls D:\workspace\MathModelAgent\backend\project\work_dir\<task_id>\checkpoint.json
```
