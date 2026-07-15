# MathModelAgent 启动说明

本文面向 Windows + Docker Desktop。本项目默认通过 Docker Compose 运行；本机前端 Node
工具链只供人工本地开发使用，agent 不应主动执行。

## 先选启动路径

| 目标 | 使用的命令 | 代码执行方式 | 适用边界 |
|---|---|---|---|
| 日常使用、验收、真实 E2B 沙箱 | `docker compose up -d --wait` | `remote`，需要 `E2B_API_KEY` | 默认且推荐 |
| E2B 暂不可用时恢复一个已有任务 | 加载 `docker-compose.local-execution.yml` | `auto`，显式允许本地 Jupyter | 仅可信单用户本机 Docker |

本地自动执行模式也提供了 Windows 一键入口。它只对当前 Compose 启动加载本地覆盖，
不会修改 `backend/.env.dev`：

```powershell
cd D:\workspace\MathModelAgent
.\scripts\docker-local-execution.ps1 -Action Start
```

该模式会在 E2B 可用时优先使用 E2B，缺少 E2B 时自动降级到本地解释器；后端会输出实际
生效的 `mode`、`allow_local` 和 E2B 是否配置，但不会输出密钥。完成后恢复默认安全模式：

```powershell
.\scripts\docker-local-execution.ps1 -Action RestoreRemote
```
| 修改前端/后端源码的人工开发 | `win_start.bat` 或本地手动启动 | 由开发者自行配置 | 不与本机 agent 前端命令混用 |

不要同时加载 `docker-compose.dev.yml` 与 `docker-compose.local-execution.yml`。完成受控本地恢复后，
务必再执行一次默认 `docker compose up -d --wait`，把后端恢复到远程沙箱安全默认值。

## 环境要求
- Docker Desktop
- Python 3.12 + uv
- Node.js 24 LTS + pnpm（Docker 前端同样使用 Node 24 LTS）

> Agent 操作注意：Windows 本机前端 Node 工具链曾异常派生大量 `node.exe`，导致系统卡死。除非用户明确授权，agent 不应主动运行 `pnpm i`、`pnpm run build`、`vue-tsc`、`vite build`、`biome`、`npx biome` 或 `node_modules\.bin\*`。前端验证优先使用 Docker Compose 服务或由用户手动运行命令后回传结果。

---

## 方案一：Docker Compose（推荐）

### 第一次启动前：配置与预检

1. 如果还没有 `backend/.env.dev`，从示例创建它；只在该文件填入自己的 provider 配置，
   不要把 key 写进 Git、聊天或日志。
2. 默认远程代码执行还需要设置 `E2B_API_KEY`。只配置 LLM provider 而没有 E2B 时，任务会在
   代码执行前安全停止，这是预期保护，不是需要关闭的错误。
3. 根目录 `.env` 仅用于可选的 Docker 字体挂载；它不能替代 `backend/.env.dev`。

```powershell
cd D:\workspace\MathModelAgent

# 仅首次执行；若 backend/.env.dev 已存在，保留已有配置，不要覆盖。
if (-not (Test-Path backend\.env.dev)) {
  Copy-Item backend\.env.example backend\.env.dev
}

# 验证 Compose 文件与变量能被解析；不会启动容器，也不会打印密钥正文。
docker compose config -q
```

`backend/.env.dev` 至少需要四个 Agent 的 `*_API_TYPE`、`*_API_KEY`、`*_MODEL`、
`*_BASE_URL`，以及默认远程模式所需的 `E2B_API_KEY`。可选的 `OPENALEX_EMAIL`、
`TAVILY_API_KEY` 等不影响基础建模链路；详见后文“常见问题”。

### 启动

```powershell
cd D:\workspace\MathModelAgent
docker compose build --pull            # 首次启动、改了依赖/Dockerfile 或更新基础镜像后执行
docker compose up -d --wait            # 等待服务健康；正常启动时可直接执行这一行
docker compose ps                      # 查看服务状态，应显示 healthy
```

### 停止

```powershell
docker compose down         # 停止并移除容器
docker compose stop         # 仅停止（保留容器）
docker compose down -v      # 停止并删除数据卷（⚠️ 清空 Redis 数据）
```

启动后访问 http://localhost:5173。Compose 将 `5173` 和 `8000` 都绑定到
`127.0.0.1`，默认只适合本机单用户使用；不要直接把开发 Compose 反向代理或暴露到公网。
后端任务注册、取消与建模审批状态目前依赖进程内 `_active_tasks`，因此正式运行必须保持单个
uvicorn worker；不要给 Compose/uvicorn 增加 `--workers`，除非先把活动任务注册与取消信号迁移到 Redis 等跨进程协调机制。
如确需在受信网络之外暴露后端，可在后端环境中设置 `API_AUTH_TOKEN=<随机令牌>`：
设置后所有非豁免 HTTP 接口要求 `Authorization: Bearer <令牌>`，WebSocket 要求
`?token=<令牌>` 查询参数；`/docs`、`/redoc`、`/openapi.json` 与 `/static/` 产物路径豁免。
注意当前前端尚未适配令牌模式，该开关仅供 API 直连部署方 opt-in，默认留空保持原行为。
`--wait` 会等待 Redis、后端和前端的本地健康检查通过，避免容器刚启动时 HTTP 探测出现
短暂的连接重置或代理 `500`。

默认 Compose 不再挂载整个前后端源码目录，避免运行配置被容器内模型代码读取；如需可信
本机热重载，显式增加开发覆盖文件：

```powershell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.dev.yml up -d --wait
```

### 启动后检查

```powershell
curl.exe http://127.0.0.1:5173/
curl.exe http://127.0.0.1:5173/api/docs
docker compose logs backend --tail=200
```

推荐再运行下面这段无模型调用的健康检查。它只确认代理与后端状态，不读取或输出 API Key：

```powershell
$status = Invoke-RestMethod http://127.0.0.1:5173/api/status
$status.backend | Select-Object status, feature_warnings
Invoke-WebRequest http://127.0.0.1:5173/api/docs -UseBasicParsing |
  Select-Object -ExpandProperty StatusCode
```

Docker 前端通过 Vite dev server 代理访问后端：浏览器请求
`http://localhost:5173/api/*` 会被转发到 Compose 内部的 `backend:8000`，
WebSocket 请求 `ws://localhost:5173/ws/task/<task_id>` 会被转发到后端
`/task/<task_id>`。如果 Docker Desktop 能正常发布后端端口，也可以直接访问
`http://127.0.0.1:8000/docs`；若宿主机端口发布异常，以 `5173/api/docs`
作为 Docker 验证入口。

`/status` 的 `backend.feature_warnings` 会列出配置存在但尚未接入主工作流的能力，
例如 `RAG_ENABLED`、通用 `HIL_ENABLED`、`FALLBACK_ENABLED`、`EVALUATOR_ENABLED`。
这些 warning 不代表后端异常，只表示对应开关仍是配置/占位，不能当作已完成能力验收。

后端 Docker 内验证：

```powershell
docker compose exec backend uv run python -m unittest app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
docker compose exec backend uv run python -m ruff check app
docker compose exec backend uv run python -m ruff check app --select S
```

> 不要持续 `docker compose logs -f`。排查时默认 `--tail=200`，最多临时扩大到 `--tail=2000`。

### 前置条件
- `backend/.env.dev` 已配置好 API Key
- Docker Desktop 正在运行

WebUI 侧边栏的 API Key 配置会通过 `/save-api-config` 应用到当前后端进程，
接口响应会标记 `scope=runtime`、`persisted=false`。它不会写回
`backend/.env.dev`；后端或容器重启后仍以 `.env.dev` 或系统环境变量为准。
前端不会持久化 API Key：页面刷新后需要重新填写，升级后的页面会清理旧版
`localStorage.apiKeys`。`persisted=false` 同时表示后端和浏览器都不会把该配置写入
持久化存储。

### 缺少 E2B 时的受控恢复与回退

默认 `CODE_INTERPRETER_KIND=remote` 没有 `E2B_API_KEY` 时，已开始的任务可能留下
`checkpoint.json`，状态为 `interrupted`。不要把 `CODE_INTERPRETER_KIND=local` 或
`ALLOW_LOCAL_CODE_EXECUTION=true` 写入普通 `backend/.env.dev` 来绕过保护。若这是可信的
单用户本机 Docker 恢复场景，可按以下顺序只对本次恢复加载覆盖文件：

```powershell
cd D:\workspace\MathModelAgent
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local-execution.yml up -d --wait

# <task_id> 来自 GET /api/tasks 或 WebUI；从已有检查点继续，不要重新提交同一题目。
curl.exe -X POST http://127.0.0.1:5173/api/modeling/<task_id>/resume
```

也可以让脚本完成启动、checkpoint 检查和续传请求：

```powershell
.\scripts\docker-local-execution.ps1 -Action Resume -TaskId <task_id>
```

该命令只接受已有 `checkpoint.json` 的任务，不会重复提交题目；任务已经完成时会直接跳过。

恢复任务完成并检查交付物后，立即切回默认模式：

```powershell
docker compose up -d --wait
docker compose ps
```

本地恢复模式仍与后端共享文件系统和网络，不能用于共享服务、公开部署或正式远程验收。它用于
验证恢复路径和生成可交付产物，不会把本地解释器变成项目的默认或正式执行器。本地覆盖还把
backend healthcheck 的等待窗口放宽到适合长时间 notebook 单元的范围，避免计算期间短暂的
`/docs` 响应超时被误判为容器故障；任务完成后仍应以 `/api/status` 和任务状态为准。

### 代码执行隔离

`CODE_INTERPRETER_KIND=remote` 是默认值，建模任务需要有效的 `E2B_API_KEY`。当 E2B
不可用但必须在单用户可信 Docker 环境中继续开发时，使用本地执行覆盖文件：

```powershell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local-execution.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local-execution.yml up -d --wait
```

该覆盖文件设置 `CODE_INTERPRETER_KIND=auto` 和 `ALLOW_LOCAL_CODE_EXECUTION=true`：有 E2B
时仍优先远程沙箱；没有 E2B 时才使用本地 Jupyter。受控覆盖对单次代码执行设置 120 秒硬上限，
并由独立 OS 级看门狗中断无 IOPub 返回的数值计算；超时任务会作为代码执行失败进入反思/失败流程，
不会继续写入冻结结果或论文。该模式只支持受控 Linux Docker：内核只
继承最小运行环境，并在 exec 前降权到镜像内专用的非 root `mma-runner` 用户；后端只临时保留
`CHOWN`、`DAC_OVERRIDE`、`SETGID`、`SETUID` 和 `KILL` 五项能力，分别用于准备/持久化共享
任务目录、完成降权和终止该降权子内核，另以不可 dump 保护作为纵深防护。`DAC_OVERRIDE` 只保留
在受信任 backend 进程中，runner 在 exec 前降权后不继承该能力。为兼容 Windows Docker 共享目录，
不强制修改 POSIX mode 位；降权、环境保护或内核生命周期管理不可用时会拒绝启动本地内核，随后会
剥离凭据并限制单元执行时长。
控制台日志只记录消息长度、类型和数量，不回显 Agent 正文、提示词、代码或图像 Base64。

这仍不是多租户/公开部署级隔离：本地 Jupyter 与后端共享容器文件系统和网络，仅适用于可信
单用户恢复开发，不能与 `docker-compose.dev.yml` 同时使用，也不得用于正式验收环境。

### 构建说明

后端镜像在 Python 基础镜像内通过带超时和重试的 `pip install uv==0.11.14`
安装 uv，不再从 `ghcr.io/astral-sh/uv:latest` 复制二进制文件。这样可以避免
网络不稳定时 GHCR token/metadata 获取失败导致 Docker 构建在依赖同步前中断，
也降低 PyPI 下载 uv 大 wheel 中途 read timeout 的概率。

### 架构
- **backend**（:8000）→ 支持 checkpoint/resume
- **frontend**（:5173）→ 通过 `/api` 和 `/ws` 代理连接 Compose 内部 backend:8000
- **redis**（内部网络）

后端的 CORS 与 WebSocket Origin 默认仅允许 `http://localhost:5173` 和
`http://127.0.0.1:5173`；若需要其他受信任 Origin，设置明确的
`CORS_ALLOW_ORIGINS` 列表，不能使用 `*`。`TRUSTED_HOSTS` 默认只允许
`localhost`、`127.0.0.1` 和 Compose 内部 `backend`，用于拒绝伪造 Host/DNS rebinding；
部署到其他受信任域名时必须同时显式扩展这两项。

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
```powershell
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\Activate.ps1
$env:ENV = 'dev'
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

**3. 启动前端（另一个新终端）**
```powershell
cd D:\workspace\MathModelAgent\frontend
pnpm run dev
```

**4. 打开浏览器** 访问 http://localhost:5173

---

## 端口说明

| 服务 | Docker Compose | 本地开发 |
|------|----------------|----------|
| Frontend | 5173 | 5173 |
| Backend | 内部 8000；前端代理入口 5173/api；宿主直连 `127.0.0.1:8000`（仅本机） | 8003 |
| Redis | 内部网络 | 6379 |

---

## 功能说明

### 下载任务工作区文件

文件面板支持单文件下载和“下载全部”。后端 `GET /download_all_url?task_id=...`
会在对应任务目录内按需生成 `all.zip`，然后返回 `/static/<task_id>/all.zip`
下载链接。压缩包会排除已有 `all.zip`、临时文件、常见缓存目录和内部恢复候选 PDF
（如 `res_recovery_candidate.pdf`），并限制单文件和总打包大小，避免把旧候选论文
混入下载包或意外打包过大的工作目录。

`/static/<task_id>/<filename>` 不是目录直出：只允许单层安全文件名，PNG/JPEG/GIF/WebP/BMP
可供页面预览，其余产物一律以附件下载。这样任务中上传或生成的 HTML/SVG 不能在后端
Origin 中作为网页执行。

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
- 快照成功时，直接恢复该快照并继续未完成阶段；为避免重放已被中断的高开销单元格，不自动执行快照之后的历史单元格
- 快照不可用时，回退到 notebook 全量重放
- 续传重放使用 `replay_code()`，只执行代码，不写入 notebook，不向前端重复推送代码单元格
- 重建完成后继续执行未完成阶段

**执行证据收束**：每个正式 `quesN` 的计算完成后，Coder 必须调用受控
`record_execution_evidence`，由后端计算文件 SHA-256 并生成 `execution_validation.json`。
若连续成功代码调用达到上限，系统会停止提供 `execute_code`，只允许该证据工具；没有受控
证据不会进入 Writer/PDF。证据引用的结果 CSV/JSON/TXT 与图表数据还必须由**当前 Coder 回合**
的实际执行新建或更新；不能把 checkpoint 中未更新的旧文件重新登记。一个 Coder 回合只允许记录
自己的 `quesN`，且一次只接受一个工具动作。任务在最终验证失败后最多定向回修一次；第二次真实失败即停止，
不要反复点击续传，而应先检查 `execution_validation_report.json` 和 `checkpoint.json` 的失败记录。

### 建模方案人工确认

设置 `HUMAN_MODEL_GATE_ENABLED=true` 后，Modeler 阶段完成时会生成
`modeling_decision.md/json`，任务状态变为 `waiting_review` 并等待人工确认。
前端任务页会定时刷新任务状态，无需手动刷新即可显示“确认建模方案并继续”按钮；点击后调用
`POST /modeling/{task_id}/approve-modeling`，后端标记方案已确认并从 Coder 阶段续跑。
如需先查看方案，可打开文件面板下载 `modeler_plan.md` 或 `modeling_decision.md`。

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
curl.exe "http://127.0.0.1:5173/api/track?task_id=<task_id>"
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
curl.exe -X POST http://127.0.0.1:5173/api/modeling `
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
- 论文附录会自动重建：附录 A 列出支撑材料，附录 B 保留任务目录发现的完整可运行脚本及
  notebook 代码单元（不含 notebook 运行输出）。每份源码会记录原始 SHA-256；为避免 TeX
  `lstlisting` 分隔符冲突，极少数危险字符串和装饰性超长分隔线会采用可逆安全编码，原始哈希
  仍用于核验。`final_acceptance_report.json -> complete_source_appendix` 会同时检查源码覆盖、
  哈希和正文代码内容，附录 A 文件清单不能替代该检查。源码中的正常 `print(...)` 是可运行代码，
  不会被当作控制台噪声删除或阻断。
- `paper_preflight_report.json` 是规则/正则驱动的格式与证据链门禁，不证明模型、求解和论证一定正确；`PASS` 后仍需人工复核数学内容。
- **数学执行与结果冻结门禁**：新任务会在工作目录写入 `problem_contract.json`，把可识别的题面固定参数和必答要求传给 Modeler/Coder。所有 solution 代码阶段先单独完成并写入 checkpoint；每个正式 `quesN` 必须通过受控 `record_execution_evidence` 写入真实执行、可行性、可计算约束、任务内结果源 SHA-256、指标与图表数据来源，模型不得手写 manifest、哈希或顶层结构。每问都必须有任务目录内的结构化数值源（通常为 `quesN_results.csv`）；manifest 的 `source.path` 必须是精确任务相对路径，数值必须有限，PNG 等图片不能单独作为数值证据。优化题还必须冻结目标值和每个实际最优决策变量（包括灵敏度情景的新决策向量），不能只记录利润差或残差。工作流仅在 `execution_validation_report.json = PASS` 后生成 `frozen_results.json`，此后才启动 Writer；摘要、正文、图题和结论中的计算数值只能使用冻结结果。缺少 manifest、notebook 有未解决执行错误、约束不满足、优化变量缺失或来源哈希变化都会阻止论文写作与任务完成；一次失败只定向回交失败题，保留已通过题的检查点。历史任务目录没有这些文件时，必须按当前版本重跑后才能作为数学验收样本。

- **Writer 预检回修与导出停止条件**：冻结通过并不保证 Writer 没有误写数值。若 `paper_preflight_report.json = FAIL` 的硬错误仅能明确归属到某个 `quesN` 正文或摘要中的 `result_consistency` 等事实冲突，系统会把冲突句和冻结事实只交回该章节 Writer 一次，然后重新预检；已通过章节不会重写。无法可靠定位的来源、附录、版式等失败不会盲目调用模型。一次回修后仍为 `FAIL` 时任务会停止在预检阶段，不生成候选 PDF；请先看报告的 `checks`/`conflicts` 和 checkpoint 中的 `last_paper_preflight_failure`，修正后再续传。`CONDITIONAL_PASS` 不触发自动改写，但仍必须按提交清单人工处理。

**门禁失败时不要先补导 PDF**：如果任务状态为 `failed` 且消息为“代码执行/数值可行性门禁未通过”，先打开任务目录的 `execution_validation_report.json`，逐问修复 `errors`、`constraints` 和 `source.path` 指出的证据缺口。此时 Writer 尚未运行，`res.pdf` 缺失是预期保护行为，使用 `export_cli` 强行导出也不能让任务变为可验收。相同任务在同一模型/provider 已连续两次失败时，按恢复规程停止自动重试；由指定决策人切换到已验证的备用 provider 配置后最多续传一次，或先人工确定可复核的低开销算法，再继续。
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
curl.exe -X POST http://127.0.0.1:5173/api/modeling/<task_id>/approve-modeling `
  -H "Content-Type: application/json" `
  -d "{\"comment\":\"建模方案确认通过\"}"
```

确认接口会把 `modeling_decision.json` 标记为 `approved`，再复用现有 checkpoint/resume 链路从 Coder 阶段继续执行，不会重跑 Coordinator 或 Modeler。

### LLM 请求超时

OpenAI-compatible、Responses 和 Anthropic provider 会使用
`LLM_REQUEST_TIMEOUT_SECONDS` 控制单次请求超时，默认 `90` 秒。部分兼容端点或较慢模型
在建模手/写作手阶段响应时间可能超过 SDK 默认值；项目同时以 `asyncio.wait_for` 强制该上限，
并关闭 SDK 内部重试，避免隐式重试把单次上限放大。LLM 层默认最多重试 3 次；如连续出现
`Request timed out`，可在 `backend/.env.dev` 中临时调大该值后重启后端。

### 结构化 LaTeX Sidecar

LaTeX sidecar 现在生成两类正文文件：

- `latex_project/sections/imported_body.tex`：完整 Markdown 一次性转换的兼容文件，便于对照和回退。
- `latex_project/sections/00_*.tex`、`01_*.tex` 等：按 Markdown 顶层标题拆分后的结构化章节文件。

生成前会对 LaTeX sidecar 专用 Markdown 做轻量兼容处理：保留已有 fenced code block，
对未 fenced 的 `# Cell n` notebook 片段补代码围栏，并在章节拆分时忽略代码块内的
`#` 注释，避免附录源码被误拆成正文章节。模板外壳同时兼容新版 Pandoc 生成的
`\pandocbounded`、`\passthrough` 图片/inline 片段，并把图片搜索路径设为
`./`、`../`、`sections/`、`figures/`，以便引用任务目录根部图片。

sidecar 与主 PDF 一样禁用 Markdown raw TeX；模型生成的 `\input`、`\write18` 等命令
不会透传给 XeLaTeX。自动 PDF/sidecar 编译显式传入 `-no-shell-escape`，手动复现也应保留
该参数。

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
uv run python -m app.tools.export_cli pdf --input path\to\res.md --output path\to\res.pdf --profile cumcm2026 --local --update-status
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
uv run python -m app.tools.export_cli pdf --input examples\pdf_export_sample\res.md --output examples\pdf_export_sample\res.pdf --profile cumcm2026 --local --font-config examples\pdf_export_sample\fonts.json
uv run python -m app.tools.export_cli latex --input examples\pdf_export_sample\res.md --work-dir examples\pdf_export_sample --profile cumcm2026
```

**方式二：导出 LaTeX sidecar 项目后手动编译**（更稳，能看到完整编译日志，也能自己再精修排版）：

```powershell
cd backend
uv run python -m app.tools.export_cli latex --input path\to\res.md --work-dir path\to\workdir --profile cumcm2026
```

导出后会在 `path\to\workdir\latex_project\` 下生成 `main.tex` 等文件；如果本机 `latexmk`/`xelatex` 在 PATH 里，命令会自动尝试编译并直接告诉你是否成功。自动编译优先尝试 `latexmk -xelatex`，失败后 fallback 到连续两次 `xelatex`；如果仍失败，`tex_export_status.json` 会记录 `compile_reason`、`compile_failure_summary` 和日志尾部。想手动复现时，进入该目录执行：

```powershell
cd path\to\workdir\latex_project
xelatex -no-shell-escape -interaction=nonstopmode main.tex
xelatex -no-shell-escape -interaction=nonstopmode main.tex
```

跑两遍是为了让目录（`\tableofcontents`）和交叉引用正确生成。当前 `default`、`cumcm2025`、`cumcm2026` 三个模板都没有用 `bibtex`/`biber`（没有独立的 `.bib` 参考文献库，参考文献是手写在正文里的 `thebibliography` 环境），所以不需要额外的 `bibtex main` / `biber main` 步骤；如果你自己往模板里加了 `.bib` 文件，编译顺序需要改成：

```powershell
xelatex -no-shell-escape -interaction=nonstopmode main.tex
bibtex main          # 或者 biber main，取决于用 bibtex 还是 biblatex
xelatex -no-shell-escape -interaction=nonstopmode main.tex
xelatex -no-shell-escape -interaction=nonstopmode main.tex
```

**手动指定字体**：不想用 profile 默认的字体名，或者本机装的是变体名称（比如公司电脑上中文字体被替换过），可以显式覆盖，用户指定的值总是优先且不会被静默替换：

```powershell
uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --profile cumcm2026 --local `
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
uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --profile cumcm2026 --local --font-config fonts.json
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
- `execution_validation_report.json = PASS`，并且存在可校验的 `execution_validation.json`、`frozen_results.json`；逐问确认 `feasible=true` 和约束来源文件仍可按 SHA-256 校验。
- `paper_preflight_report.json` 中 `freeze_integrity`、`result_consistency`、`figure_result_consistency`、`infeasible_optimality`、`algorithm_evidence` 和 `reference_relevance` 均通过；这些检查用于拦截无执行证据的算法、不可行解被写成最优、图文数值矛盾和明确跨领域引用。
- 若 `paper_preflight_report.json = CONDITIONAL_PASS`，`submission_audit_report.json`
  会降级为 `WARN`，表示主交付已生成但仍有条件项需要人工接受或修正；正式提交前优先修到
  `PASS`。
- `paper_preflight_report.json -> checks.images.unused_generated = []`。已登记在附录A
  支撑材料表中的 `图片文件` 不算 unused；真正未引用且未登记的生成图仍需清理、引用或接受
  conditional 风险。
- `pdf_visual_check.json = PASS`。
- `submission_audit_report.json = PASS`（严格字体门禁）。
- PDF 正文和附录外不应粘贴 `print(`、`printf`、`console.log` 等批量控制台输出；附录 B 的完整源码中出现这些正常代码语句是允许的。
- `candidate_manifest.json` 登记 `notebook.ipynb`、图片、数据文件等支撑材料。
- 对 CUMCM 2026 正式提交：论文附录须实际包含全部完整、可运行源程序；检查
  `final_acceptance_report.json -> complete_source_appendix = PASS`，再人工运行关键代码并复核其与正文结果一致。

### 自动提交审核门禁

任务完成时会自动生成：

- `submission_audit_report.json`
- `submission_audit_report.md`

该报告汇总主交付文件、`execution_validation_report.json`、`paper_preflight_report.json`、`pdf_visual_check.json`
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

### 测试 -1：启动与代理烟雾测试（不调用模型）

每次修改 Compose、启动说明、代理配置或重建镜像后，先运行这一组检查。它不会提交题目，
因此不消耗模型额度，也不会读取配置中的密钥：

```powershell
cd D:\workspace\MathModelAgent
docker compose config -q
docker compose up -d --wait
docker compose ps

$frontendResponse = Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing
$docsResponse = Invoke-WebRequest http://127.0.0.1:5173/api/docs -UseBasicParsing
$status = Invoke-RestMethod http://127.0.0.1:5173/api/status

if ($frontendResponse.StatusCode -ne 200 -or $docsResponse.StatusCode -ne 200 -or $status.backend.status -ne 'running') {
  throw 'Docker 前端、/api 代理或后端健康检查未通过。'
}
'启动与代理烟雾测试通过'
```

通过标准：`docker compose ps` 中 redis、backend、frontend 都是 `healthy`；前端首页与
`/api/docs` 返回 200；`/api/status` 的 `backend.status` 为 `running`。容器健康态以
`docker compose ps` 的 `healthy` 为准。若失败，先运行
`docker compose logs backend --tail=200`，不要持续 follow 日志。

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
- `paper_preflight_report.json -> checks.images.unused_generated = []`，除非明确接受未引用且
  未登记图片的 conditional 风险
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
- CUMCM 2026 正式投稿前：确认论文附录实际包含完整、可运行源程序。默认自动输出会写入完整
  脚本/notebook 代码单元及 SHA-256；只有显式启用 `paper_appendix_config.json -> mode=key` 时才是
  关键摘录展示，且此模式不能得到 `TECHNICAL_PASS`，技术报告也不能替代人工复核。
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

恢复边界：后端启动时会把因进程重启遗留的 `running`、`resuming`、`finalizing`
状态改为 `interrupted`，不会把已经完成的任务重跑。每个新任务在 Coordinator/Modeler
之前即保存不含凭据的 `task_request.json`；因此早期规划失败、尚未生成 `checkpoint.json`
时，仍可通过 `POST /modeling/{task_id}/resume` 从原始题面重新思考并开始。

代码执行验证第一次失败会自动进行一次仅针对失败子题的回修，已通过子题保持冻结。连续两次
真实失败后系统停止自动重试；指定决策人只有在确实切换已验证 provider 或确认低开销可复核
算法后，才能显式发起一次恢复，且每个任务最多一次：

```powershell
curl.exe -X POST http://127.0.0.1:5173/api/modeling/<task_id>/resume `
  -H "Content-Type: application/json" `
  -d '{"recovery_mode":"provider_changed","note":"已切换到已验证的 provider"}'
```

`recovery_mode` 也可为 `low_cost_algorithm`。恢复上下文只会指导 Agent 校正未完成或未通过
的阶段，禁止写入最终论文；外部 provider、执行环境或最终技术验收仍可能失败，不能承诺无条件产出。

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
curl.exe -X POST http://127.0.0.1:5173/api/modeling `
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

## 论文收尾 P0-P2 门禁（2026-07）

当前论文链路按三层收尾：

- **P0 产物新鲜度与状态一致性**：任务先进入 `finalizing`，基础 DOCX / audit / manifest / final acceptance 任一步异常都会形成真实失败；`task_status.json` 是任务状态权威来源。PDF、DOCX 重导前会删除旧文件，避免旧产物冒充本轮结果。`export_status.json` 与 `docx_export_status.json` 分别记录 Markdown 源哈希、输出哈希和导出结果。
- **P1 结构与全页视觉质量**：预检会拒绝重复参考文献、非法 Markdown 表格、表题紧贴表格等结构问题；`pdf_visual_check.json` 默认扫描全部页面，并把 `pdf_sha256`、`pages_checked`、`page_count` 写入报告。提交审计只接受与当前 `res.md` / `res.pdf` 哈希一致且覆盖全部页面的报告。
- **P2 论文表达与复现闭环**：后处理会为正文中缺少邻近“图1、图2……”引用的图片补入中性图号说明（附录和代码块不改、重复运行不重复插入）；人工仍须确认图号与上下文语义匹配。连续型线性规划若把小数结果直接写成“46.67件”等，会产生 `continuous_quantity_wording` 条件警告，应改写为“连续生产当量”或另建整数规划。PDF/LaTeX 代码附录使用 `\footnotesize` 等宽字体，在保持可读的前提下减少只剩少量代码的尾页。

`candidate_manifest.json` 现使用 schema `1.1`，包含 `artifact_set_id` 和主产物 SHA-256；内部审查目录、失败尝试目录和 `latex_project/figures/` 的 sidecar 复制图片不会进入正式候选图片列表。严格技术验收仍不替代模型、推导、引用和逐页排版的人工复核。
