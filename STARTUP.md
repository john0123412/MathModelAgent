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
curl.exe http://127.0.0.1:8000/docs
curl.exe http://127.0.0.1:5173/
docker compose logs backend --tail=200
```

后端 Docker 内验证：

```powershell
docker compose exec backend uv run python -m unittest app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
docker compose exec backend uv run python -m ruff check app
```

> 不要持续 `docker compose logs -f`。排查时默认 `--tail=200`，最多临时扩大到 `--tail=2000`。

### 前置条件
- `backend/.env.dev` 已配置好 API Key
- Docker Desktop 正在运行

### 架构
- **backend**（:8000）→ 支持 checkpoint/resume
- **frontend**（:5173）→ 连接 :8000
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
| Backend | 8000 | 8003 |
| Redis | 内部网络 | 6379 |

---

## 功能说明

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

### 导出模板选项（Export Profile）

**这是新增的可选功能，不影响默认导出行为**——不传 `export_profile` 或传 `default` 时，导出结果与之前完全一致。

**可选值**：
- `default`（默认）：保持原有 Markdown/DOCX/PDF/LaTeX sidecar 导出行为
- `cumcm2025`：套用 2025 年高教社杯/国赛（CUMCM）格式规范
- `cumcm2026`：套用 2026 年高教社杯/国赛（CUMCM）格式修订稿；PDF 不生成目录，也不启用 pandoc 自动章节编号，避免与 Markdown 模板中的 `一、`、`1.1` 手写编号叠加
- `huashubei`：华数杯模板，仅用于华数杯任务；参加高教社杯/国赛时请使用 `cumcm2026`

**如何选择**：前端提交页已经暴露“排版”选择，默认使用 `cumcm2026`；也可以直接调用 `POST /modeling` 表单字段 `export_profile`（`Form(ExportProfile.DEFAULT)`），例如：

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
2. **LaTeX sidecar**：沿用 gmcmthesis 资源目录，但模板键为 `zh/cumcm2026-gmcmthesis`，电子版从摘要页开始；`latex_project/main.tex` 默认输入结构化 `sections/*.tex`，同时保留 `sections/imported_body.tex` 作为兼容审计文件。

> 当前若目标赛事是高教社杯全国大学生数学建模竞赛，应优先使用 `export_profile=cumcm2026`；不要使用 `huashubei`，后者是华数杯 profile。

**已知限制**：
- LaTeX sidecar 编译产物（`latex_project/`）属于候选导出，提交前仍需人工核对（`candidate_manifest.json` 中会标注 `known_risks`）
- **字体**：PDF/LaTeX sidecar 优先使用官方格式规定的 Times New Roman/SimSun 等正式字体；精简版 Docker 镜像默认不含这些 Windows/Office 专有字体，会在编译期自动检测（`fc-match` / fontspec `\IfFontExistsTF`）并回退到免费等效字体，不影响能否编译成功，但正式提交前建议人工核对排版观感是否符合要求。两类字体的 fallback 途径不同：
  - **英文/Latin 字体**（Times New Roman → Liberation Serif、Courier New → Liberation Mono、Arial → Liberation Sans）：可通过构建时开启 `INSTALL_MS_FONTS=true` 装真正的 Microsoft Core Fonts（`ttf-mscorefonts-installer`），从而不必 fallback：
    ```bash
    docker compose build --build-arg INSTALL_MS_FONTS=true backend
    ```
    该选项默认关闭，因为它需要接受 Microsoft 的字体许可协议（EULA）并在构建时从外部镜像下载字体二进制文件，不适合作为默认公开镜像行为，仅建议在你自己私有构建、且已知晓并接受该许可与网络依赖时开启。
  - **中文字体**（SimSun/SimHei/KaiTi/STXinwei/LiSu）：**`INSTALL_MS_FONTS` 对此无效**——`ttf-mscorefonts-installer` 只包含 Times New Roman/Arial/Courier New 等英文字体，不含任何中文 Windows 字体。这些中文字体本身没有可合法分发的开源渠道（不像 Liberation 之于 Times New Roman那样有官方免费克隆），因此容器内始终 fallback 到 `fonts-noto-cjk`/`texlive-lang-chinese` 提供的 Noto Serif/Sans CJK SC、AR PL KaitiM GB，没有"装包补全"的选项。如需真正的 SimSun/SimHei/KaiTi 排版效果，只能在已合法安装这些字体的宿主机（如 Windows 本地开发环境）上编译，或自行挂载你合法持有的字体文件到容器内。

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

### 结构化 LaTeX Sidecar

LaTeX sidecar 现在生成两类正文文件：

- `latex_project/sections/imported_body.tex`：完整 Markdown 一次性转换的兼容文件，便于对照和回退。
- `latex_project/sections/00_*.tex`、`01_*.tex` 等：按 Markdown 顶层标题拆分后的结构化章节文件。

`latex_project/main.tex` 默认输入结构化章节文件，`tex_export_status.json` 会记录：

- `structured_sections`
- `structured_section_count`
- `main_uses_structured_sections`

如果 Markdown 没有可拆分的顶层标题，sidecar 会回退到输入 `sections/imported_body.tex`。
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
uv run python -m app.tools.export_cli pdf --input path\to\res.md --output path\to\res.pdf --profile cumcm2025 --local
```

- `--local` 是关键参数：不加它会走跟 Docker 一样的策略（也能跑，但检测到 Times New Roman 缺失时不会给你打印本机安装状态提示，只写日志）；加了以后会明确报告每个字体是否命中本机已安装的版本，并且——只要你没有用下面的 `--mainfont` 等参数手动指定——官方字体检测到确实已经装了才会使用，检测不到就按开源字体回退并打印原因，不会不声不响换成别的字体。
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

导出后会在 `path\to\workdir\latex_project\` 下生成 `main.tex` 等文件；如果本机 `latexmk`/`xelatex` 在 PATH 里，命令会自动尝试编译一次并直接告诉你是否成功。如果想自己手动编译（或自动编译失败想看到完整报错），进入该目录执行：

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
- 工作目录生成 `res.md`、`res.json`、`res.docx`、`candidate_manifest.json`
- 续传相关测试应生成 `checkpoint.json`、`variable_snapshot.pkl`、`variable_snapshot_meta.json`
- 后端日志出现 `变量快照已恢复` 或 `快照后增量重放`
- 如果容器未安装 `pandoc`，`res.pdf` 和 LaTeX sidecar 可能被跳过；只要 Markdown/Word/JSON 成功，不视为主流程失败

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
- 如果本机装了 pandoc + latexmk/xelatex，`latex_project/main.tex` 应包含 `CUMCM 2026 LaTeX sidecar`，且 `latex_project/gmcmthesis.cls`、`latex_project/figures/logo2025.png` 等模板资源已被复制
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
