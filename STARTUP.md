# MathModelAgent 启动说明

本文面向 Windows + Docker Desktop。本项目默认通过 Docker Compose 运行；本机前端 Node
工具链只供人工本地开发使用，agent 不应主动执行。

## 先选启动路径

| 目标 | 使用的命令 | 代码执行方式 | 适用边界 |
|---|---|---|---|
| 当前可信单用户本机、未配置 E2B | `docker compose up -d --wait` | `local`，由根目录 `.env` 持久加载受限覆盖 | 本机默认 |
| 已配置 E2B 的共享/远程环境 | `docker-local-execution.ps1 -Action UseRemote` | `remote` | 显式选择，切换前强制验证 E2B |
| 修改前端/后端源码的人工开发 | `win_start.bat` 或本地手动启动 | 由开发者自行配置 | 不与本机 agent 前端命令混用 |

可信本地执行模式也提供 Windows 一键入口，不会修改 `backend/.env.dev`：

```powershell
cd D:\workspace\MathModelAgent
.\scripts\docker-local-execution.ps1 -Action Start
```

该模式明确选择本地解释器，不会因 E2B 配置变化而切换后端；后端会输出实际
生效的 `mode`、`allow_local` 和 E2B 是否配置，但不会输出密钥。只有确认已配置 E2B 后，
才能显式切换 remote：

```powershell
.\scripts\docker-local-execution.ps1 -Action UseRemote
```

旧的 `RestoreRemote` 动作仅作为兼容别名保留，同样会先验证 E2B；缺少 E2B 时脚本会在
改变容器之前拒绝操作，避免把可用的 local 后端切换成不可执行代码的 remote 后端。

不要同时加载 `docker-compose.dev.yml` 与 `docker-compose.local-execution.yml`。当前无 E2B
工作站应在根目录 `.env` 保留 `COMPOSE_FILE`，使普通 `docker compose up` 始终使用本地模式。
不要用手写的 `-f docker-compose.yml -f docker-compose.override.yml` 命令绕过该本机默认值。

## 环境要求
- Docker Desktop
- Python 3.12 + uv
- Node.js 24 LTS + pnpm（Docker 前端同样使用 Node 24 LTS）

一键体检（可选）：`python skills/doctor/scripts/check_env.py` 按 required / recommended /
optional 三级输出依赖就绪状态、版本与安装建议（含国内镜像方案），`--format json` 供脚本
消费；该脚本只检查、从不安装，安装前仍需人工确认。

> Agent 操作注意：Windows 本机前端 Node 工具链曾异常派生大量 `node.exe`，导致系统卡死。除非用户明确授权，agent 不应主动运行 `pnpm i`、`pnpm run build`、`vue-tsc`、`vite build`、`biome`、`npx biome` 或 `node_modules\.bin\*`。前端验证优先使用 Docker Compose 服务或由用户手动运行命令后回传结果。

---

## 方案一：Docker Compose（推荐）

### 第一次启动前：配置与预检

1. 如果还没有 `backend/.env.dev`，从示例创建它；只在该文件填入自己的 provider 配置，
   不要把 key 写进 Git、聊天或日志。
2. 当前可信单用户本机没有 E2B，应在根目录 `.env` 持久加载本地执行覆盖；共享或远程部署
   必须改用 E2B，不能启用本地解释器。
3. 根目录 `.env` 只保存 Compose 选择和可选字体路径，不能替代 `backend/.env.dev`，也不得
   写入 provider 凭据。

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
`*_BASE_URL`；只有显式 remote 模式需要 `E2B_API_KEY`。可选的 `OPENALEX_EMAIL`、
`TAVILY_API_KEY` 等不影响基础建模链路；详见后文“常见问题”。

> 配置缺失的失败时机：任一角色缺少模型 ID 或 API Key 时，后端在任务启动前即报错并
> 一次性列出全部缺失项，不会进入 Agent 循环后才暴露；补齐 `backend/.env.dev` 后重试即可。

### 启动

```powershell
cd D:\workspace\MathModelAgent
docker compose build --pull            # 首次启动、改了依赖/Dockerfile 或更新基础镜像后执行
docker compose up -d --wait            # 等待服务健康；正常启动时可直接执行这一行
docker compose ps                      # 查看服务状态，应显示 healthy
```

> 容器命名提示：容器名为 `mathmodelagent_john_{redis,backend,frontend}`（个人部署口径，
> 定义于 `docker-compose.override.yml`）。自旧名称迁移后的首次 `docker compose up` 会重建
> 对应容器，属预期行为；数据卷按服务定义挂载，不受容器改名影响。

后端镜像通过官方 Debian HTTPS 源分批安装 CJK、Pandoc 和 TeX Live，避免 Docker Desktop
在大包 HTTP 下载中断或一次性 apt 安装触发内存峰值；不要把这些层合回单条 apt 命令。默认镜像
保留主工作流、SciPy/scikit-learn/statsmodels 与完整导出工具链；`sentence-transformers` 和
`xgboost` 分别是 `semantic-search`、`modeling-extensions` 可选能力，不会在基础镜像中隐式拉取
Torch/CUDA/NCCL。当前主工作流没有接入前者；需要后者的定制部署应在专用镜像中显式安装对应 extra。

若 Docker Desktop 能解析 provider 域名却无法完成 TLS 握手，而 Windows 已有本机 HTTP CONNECT
代理，基础/remote Compose 可在 `backend/.env.dev` 显式设置
`LLM_OUTBOUND_PROXY=http://host.docker.internal:<端口>` 后重启 backend。当前可信本机
local-execution 覆盖默认直连，以免 `backend/.env.dev` 中的旧代理在重建后阻断全部 Agent；该模式如需
代理，应改在根目录 `.env` 显式设置
`MMA_LLM_OUTBOUND_PROXY=http://host.docker.internal:<端口>` 后执行 `docker compose up -d --wait`。
两种设置都只供 LLM 客户端使用；程序仍会校验最终 provider URL 为公开 HTTPS 地址并禁止重定向，
不会自动读取 `HTTP_PROXY` / `HTTPS_PROXY`。

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

### Agent 调用 Docker 后端（无前端，路线图 2026-09-03）

纯后端模式是外层执行 Agent 的正式入口，前端为可选（`--profile frontend`）：

```powershell
# 仅后端+Redis（Agent 推荐，不依赖 5173 前端代理）
docker compose up -d --wait
curl.exe http://127.0.0.1:8000/status
curl.exe http://127.0.0.1:8000/docs

# 需要前端时显式启用
docker compose --profile frontend up -d --wait
curl.exe http://127.0.0.1:5173/
```

任务客户端（固定 `backend/.venv`，不读取 provider 凭据）：

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.tools.task_client doctor --base http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m app.tools.task_client submit --ques "题目..." --comp CHINA --profile cumcm2026 --file data.xlsx --require-model-review --receipt receipt.json
.\.venv\Scripts\python.exe -m app.tools.task_client inspect --task-id <id> --base http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m app.tools.task_client events --task-id <id> --after 0 --limit 20
.\.venv\Scripts\python.exe -m app.tools.task_client guide --task-id <id> --role modeler --content "请加强约束检验"
.\.venv\Scripts\python.exe -m app.tools.task_client approve-model --task-id <id>
.\.venv\Scripts\python.exe -m app.tools.task_client review-results --task-id <id> --action approve --review-id <id> --base http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m app.tools.task_client artifacts --task-id <id>
```

`--receipt` 与 `Idempotency-Key` 保证重复提交返回同一任务；`inspect/events/artifacts/review/packet` 支持游标与版本绑定；`guide --guidance-id` 区分已接收/已消费；下载链接返回 `path`（相对）与 `download_url_absolute`（可选绝对），Agent 用 `8000` 基址拼接即可，无需前端代理。

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

### 缺少 E2B 时的可信本地默认与回退

基础 Compose 的安全默认仍是 `remote`；但当前无 E2B 的可信单用户工作站通过根目录 `.env`
持久加载 `docker-compose.local-execution.yml`。不要把 `CODE_INTERPRETER_KIND=local` 或
`ALLOW_LOCAL_CODE_EXECUTION=true` 写入普通 `backend/.env.dev`，也不要在共享服务启用该覆盖。
需要显式启动或修复本机配置时运行：

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

若本机暂时无法配置 E2B，且确认这是不接收不可信输入的单用户 Docker 环境，可在仓库根目录
`.env` 中持久加载同一受限覆盖。Windows Docker Desktop 配置如下：

```dotenv
COMPOSE_FILE=docker-compose.yml;docker-compose.override.yml;docker-compose.local-execution.yml
# 可选：仅当本机直连 provider 的 TLS 失败且本机 HTTP CONNECT 代理可用时设置。
# MMA_LLM_OUTBOUND_PROXY=http://host.docker.internal:<端口>
```

随后普通命令即会加载覆盖，无需每次重复 `-f`：

```powershell
docker compose up --build -d --wait
curl.exe http://127.0.0.1:8000/status
```

`/status` 的 `code_execution` 必须显示 `status=ready`、`configured_kind=local`、
`selected_kind=local`、`local_execution_allowed=true`。接口只报告 E2B 是否配置，不返回 Key。

只有准备好有效 E2B 后才切换 remote，并使用带前置验证的脚本：

```powershell
.\scripts\docker-local-execution.ps1 -Action UseRemote
```

本地模式仍与后端共享文件系统和网络，不能用于共享服务、公开部署或远程多租户验收。它是当前
可信单用户工作站的默认执行器，但不是项目面向其它部署环境的全局安全默认。本地覆盖还把
backend healthcheck 的等待窗口放宽到适合长时间 notebook 单元的范围，避免计算期间短暂的
`/docs` 响应超时被误判为容器故障；任务完成后仍应以 `/api/status` 和任务状态为准。

### 代码执行隔离

基础 Compose 的 `CODE_INTERPRETER_KIND=remote` 需要有效 `E2B_API_KEY`。当前可信单用户本机
通过根目录 `.env` 自动加载本地执行覆盖；需要显式确认时也可运行：

```powershell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local-execution.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local-execution.yml up -d --wait
```

该覆盖文件设置 `CODE_INTERPRETER_KIND=local` 和 `ALLOW_LOCAL_CODE_EXECUTION=true`，明确选择
本地 Jupyter，不会因 E2B 配置变化而切换后端。受控覆盖对单次代码执行设置 300 秒硬上限，
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

后端在 `RECOVER_STALE_TASKS_ON_STARTUP=true`（默认值）时，会把遗留的运行状态标记为
`interrupted`，以便用户续传。`python -m unittest` 进程（包括按目录 discover 的 TestClient
测试）会自动禁用这项启动期写入，即使测试包初始化顺序不同也不会改写共享 Docker 任务；其他
脚本或临时 FastAPI 生命周期测试仍应显式设置
`RECOVER_STALE_TASKS_ON_STARTUP=false`。生产/正常 Docker 运行保持默认 `true`，以便真实遗留任务
能被发现并续传。

**执行证据收束**：每个正式 `quesN` 的计算完成后，Coder 必须调用受控
`record_execution_evidence`，由后端计算文件 SHA-256 并生成 `execution_validation.json`。
若连续成功代码调用达到上限，系统会停止提供 `execute_code`，只允许该证据工具；没有受控
证据不会进入 Writer/PDF。证据引用的结果 CSV/JSON/TXT 与图表数据还必须由**当前 Coder 回合**
的实际执行新建或更新；不能把 checkpoint 中未更新的旧文件重新登记。一个 Coder 回合只允许记录
自己的 `quesN`，且一次只接受一个工具动作。任务在最终验证失败后最多定向回修一次；第二次真实失败即停止，
不要反复点击续传，而应先检查 `execution_validation_report.json` 和 `checkpoint.json` 的失败记录。
若本轮写出标准 `quesN_acceptance_metrics.csv`，后端会从该表读取 ModelPlan 指标的精确数值、方向和来源，
并复算 `数值/目标值/是否达标`；`quesN_constraint_check.csv` 的左右端、比较符与状态也会复算。表内自相矛盾、
显示值舍入后无法复核，或证据虽已写入但 `feasible=false` 时，都必须回到 Coder 定向修复，不能进入 Writer。
若表按压力、时段等场景把指标命名为 `原指标键_场景`，后端会按 ModelPlan 比较方向取最坏场景，并将对应
metric/constraint 的精确数值和 SHA-256 来源统一绑定到该验收表；这不会把任何不达标的场景折算为通过。

### 建模方案人工确认

设置 `HUMAN_MODEL_GATE_ENABLED=true` 后，Modeler 阶段完成时会生成
`modeling_decision.md/json`，任务状态变为 `waiting_review` 并等待人工确认。
前端任务页会定时刷新任务状态，无需手动刷新即可显示“确认建模方案并继续”按钮；点击后调用
`POST /modeling/{task_id}/approve-modeling`，后端标记方案已确认并从 Coder 阶段续跑。
如需先查看方案，可打开文件面板下载 `modeler_plan.md` 或 `modeling_decision.md`。若审查发现模型、硬约束或验收口径有误，可在尚未批准时用一次
`POST /modeling/{task_id}/revise-modeling` 退回完整意见；后端只重新运行 Modeler，并再次停在 `waiting_review`，不会直接进入 Coder。
审批时后端会校验 `modeling_decision.json`、`modeler_plan.json` 与 `checkpoint.json` 中的规范化计划
SHA-256 是否一致。续传若因旧计划与当前约束冲突而重建方案，也会清除旧审批并重新停在
`waiting_review`；必须审阅并批准新计划，不能沿用旧决策直接进入 Coder。

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

### 任务级模板覆盖（导入最新竞赛包）

如果赛事发布了新的 Word 参考模板，或队伍已经取得需要当前任务采用的格式包，优先使用
任务级覆盖，不要直接改写仓库的公共 `export_profile` 或模板资源。覆盖只作用于一个任务，
并将 DOCX 复制到任务目录 `template_overrides/`，在 `export_template_override.json` 中记录
DOCX 与版式合同的 SHA-256。`template show` 会重新校验这些哈希；发现文件被替换或清单不一致
时会 fail closed。导入接口只接受安全的 `.docx`（不是 `.doc`、符号链接或任意压缩包），
目前只允许 `cumcm2025` 和 `cumcm2026`。

仓库内的中文竞赛格式（包括用户导入的格式合同）是**用户指定基线**，不是应用对竞赛官方规则
的认证；`huashubei` 仅作华数杯参考 profile，不能把它的版式、页数或字段写成高教社杯 CUMCM
官方条款。系统会在审计中固定标记 `source=user_supplied_unverified`、`official_rule=false`，
即使文件确实来自官方包，也必须由队员对当日最新官方包和提交系统再次核对。

先准备一个从官方包或队伍资料取得的普通 `.docx` 和一个受限 JSON 合同。在 `backend/` 目录
（已激活项目环境时可将 `uv run python` 换成 `python`）执行：

```powershell
cd D:\workspace\MathModelAgent\backend
uv run python -m app.tools.export_cli template install `
  --task-id <task_id> `
  --profile cumcm2026 `
  --docx-template "D:\format-package\official.docx" `
  --format-contract "D:\format-package\format.json" `
  --label "队伍取得的中文竞赛格式基线 2026-08"

# 校验当前任务的模板/合同哈希，并显示 source=unverified 审计字段
uv run python -m app.tools.export_cli template show `
  --task-id <task_id> --profile cumcm2026

# 必须执行：不调用 Provider、不重跑数值，只重建全部论文交付物和审计
uv run python -m app.tools.export_cli task-refresh `
  --task-id <task_id> --profile cumcm2026 --local
```

`task-refresh` 在预检无硬失败（`PASS` 或 `CONDITIONAL_PASS`）时继续重建交付物；
只有硬门禁 `FAIL` 才拒绝。`huashubei` profile 的视觉/预检阈值另有部署放宽口径
（内容边距 0.6cm、正文 35 页、关键词任意页、claim_trace ≤20 条不阻断），
详见 `docs/md/PDF模板导出说明.md`。

`--local` 只让刷新时优先检测 Windows 正式字体；没有该参数也不会改变模板合同。Docker
调用时，两个输入文件必须先位于容器可见路径（例如任务目录的
`/app/project/work_dir/<task_id>/`），然后执行同一组命令：

```powershell
docker compose exec backend uv run python -m app.tools.export_cli template install `
  --task-id <task_id> --profile cumcm2026 `
  --docx-template /app/project/work_dir/<task_id>/official.docx `
  --format-contract /app/project/work_dir/<task_id>/format.json
docker compose exec backend uv run python -m app.tools.export_cli template show `
  --task-id <task_id> --profile cumcm2026
docker compose exec backend uv run python -m app.tools.export_cli task-refresh `
  --task-id <task_id> --profile cumcm2026
```

版式合同的完整安全结构示例（字段之外的 TeX、脚本、任意 Pandoc 参数都会被拒绝）如下：

```json
{
  "schema_version": "mma.export-format-contract.v1",
  "label": "队伍取得的中文竞赛格式基线 2026-08",
  "docx": {
    "body_font_east_asia": "SimSun",
    "body_font_ascii": "Times New Roman",
    "body_font_size_half_points": 24,
    "body_line_spacing_twips": 240,
    "body_line_rule": "auto",
    "body_start_page_break": true
  },
  "pdf": {
    "variables": {
      "papersize": "a4",
      "fontsize": "12pt",
      "linestretch": "1.0",
      "geometry": "left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm",
      "CJKmainfont": "SimSun"
    },
    "min_content_margin_cm": 2.5
  },
  "preflight": {
    "min_abstract_paragraphs": 2,
    "require_references": true,
    "require_reference_style": true,
    "body_min_pages": 8,
    "body_max_pages": 20
  }
}
```

合同中的 PDF 部分只允许字体、字号、行距、几何边距和 A4 等 allowlist 变量；DOCX 部分只
记录安全的字体/字号/行距/正文起始分页等样式。合同不会执行任意 TeX，也不会把“官方”写入
审计结论。`task-refresh` 成功后应检查 `res.md`、`res.docx`、`res.pdf`、`latex_project/`、
`paper_preflight_report.json`、`pdf_visual_check.json`、`submission_audit_report.json`、
`candidate_manifest.json` 和 `final_acceptance_report.json` 的当前哈希；技术报告通过仍不替代
队员逐页核对最新官方包、数学内容、匿名/诚信声明和提交系统要求。

**已知限制**：
- `cumcm2026` 当前复用 2025 年 `gmcmthesis` 模板资源目录和 `format2025_reference.docx`
  的 Word 样式作为修订稿口径实现；2026 正式模板文件发布后，需要重新复核并替换
  LaTeX 模板与 DOCX reference-doc。
- LaTeX sidecar 编译产物（`latex_project/`）属于候选导出，提交前仍需人工核对（`candidate_manifest.json` 中会标注 `known_risks`）。主交付链路是 `res.md`、`res.docx`、`res.pdf` 和 `res.json`。
- PDF 视觉检查是低成本后验检查，会覆盖 A4、非空、文本可提取、20MB 文件大小、
  摘要首页、无目录、正文 20 页以内（当前用户指定的内部基线）、物理边缘越界和 CUMCM 2.5cm 内容边距风险；
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
- **主 Agent（Codex / Gemini Antigravity / 对话 Agent）/ 人工执行质量复核门禁**：冻结后会先生成 `execution_quality_review.json/md`。结果表只要明确标记“不达标/失败”或出现 NaN/Inf，任务就停在 `waiting_quality_review`，Writer 不会启动；启用 `require_model_review=true` 时，即使机器筛查为 `PASS` 也会暂停，因为机器筛查不证明假设、量纲、守恒、推导和领域结论正确。审查者先读取题面、ModelPlan、代码、结果 CSV 和复核报告，再调用 `POST /modeling/<task_id>/execution-review`。请求 `{"action":"repair","review_id":"报告中的编号","failed_subtasks":["ques2"],"comment":"具体可执行修正意见"}` 会只让指定子题回到 Coder，并使依赖旧冻结事实的 Writer 文本失效；请求 `{"action":"approve","review_id":"报告中的编号","comment":"逐题复核依据和风险接受理由"}` 才会进入 Writer。审批只绑定当前结果文件哈希，结果变化后必须重审；返修最多一次，普通 `/resume` 不能绕过该状态。直接手改 CSV、manifest、冻结结果或论文数值不属于可信接管流程。

- **Writer 预检回修与导出停止条件**：冻结通过并不保证 Writer 没有误写数值。若 `paper_preflight_report.json = FAIL` 的硬错误仅能明确归属到某个 `quesN` 正文或摘要中的 `result_consistency` 等事实冲突，系统会把冲突句和冻结事实只交回该章节 Writer 一次，然后重新预检；已通过章节不会重写。无法可靠定位的来源、附录、版式等失败不会盲目调用模型。一次回修后仍为 `FAIL` 时任务会停止在预检阶段，不生成候选 PDF；请先看报告的 `checks`/`conflicts` 和 checkpoint 中的 `last_paper_preflight_failure`，修正后再续传。`CONDITIONAL_PASS` 不触发自动改写，但仍必须按提交清单人工处理。

- **冻结后受控论文候选修复（仅技术复核/人工接管）**：若冻结结果、当前 Writer 各章节和哈希完整，但 `paper_preflight_report.json = FAIL` 且自动 Writer 回修已停止，不能直接手改 `res.md`。审查者可在任务目录 `internal/` 写入完整章节替换 JSON（`sections` 必须覆盖当前所有 Writer 阶段，另附 `comment`），再在 **backend 容器内**运行 `docker compose exec backend uv run python -m app.tools.paper_repair_candidate_cli <task_id> internal/<candidate>.json`，最后调用普通 `POST /modeling/<task_id>/resume` 触发正式预检与导出。该入口仅接受冻结状态、一次未用的论文修复预算和当前预检 `FAIL`；它先在隔离副本预检，且只能同步更新论文 Markdown/JSON 与对应 Writer hand-off，不调用 provider，也不能修改代码、结果 CSV/XLSX、执行证据或冻结结果。候选应用成功不等于竞赛人工验收，仍须检查重建后的 PDF/DOCX、提交规则和建模口径。

- **正式 CUMCM 编辑质量门禁（内部口径，不是官方页数规定）**：`cumcm2025` 与 `cumcm2026` 的正式导出会自动启用 `cumcm_formal`。预检要求正文（不含摘要、参考文献和附录）至少 5000 个内容字符，并要求每个正式 `quesN` 至少有一幅真正的结果图和一张结果表。所有这些图表必须在任务目录的 `paper_assets_manifest.json` 中绑定 `quesN`、任务内数值 `source_paths` 及当前 SHA-256；来源变更后必须重绘并刷新清单。PDF 视觉检查还以当前用户指定的内部质量阈值检查摘要不少于 450 字符、摘要首页文字覆盖率和正文 10--20 页。报告会明确 `official_rule=false`，不得将上述阈值表述为竞赛官方要求；它们用于阻止“短稿、空白摘要页、重复示意图或无来源表格”被误标为正式范文。

- **已完成论文的受控编辑质量返修**：若任务已在 `paper_preflight_passed` 或 `completed`，但重新执行上述内部编辑质量预检后为 `FAIL`，可在 **backend 容器内**运行 `docker compose exec backend uv run python -m app.tools.paper_repair_candidate_cli <task_id> internal/<candidate>.json --editorial-quality`。它使用独立的一次 `editorial_repair_attempts` 预算，要求冻结结果与完整 Writer hand-off 均仍有效，并先在隔离副本通过同一套严格预检；成功后只更新论文 Markdown/JSON、Writer hand-off 与候选审计，再由普通 `POST /modeling/<task_id>/resume` 做纯导出。该路径不调用 provider，不能更改代码、数值结果、执行证据或冻结结果。

- **已完成论文的确定性版式重排**：若人工 PDF 复核发现可由后处理/渲染器修正的纯版式问题（例如 Markdown 三级标题被排成普通正文），不得直接手改已完成任务的 `res.md`。在冻结结果、完整 Writer hand-off、当前预检 PASS 和主产物哈希均完整时，可在 **backend 容器内**运行 `docker compose exec backend uv run python -m app.tools.paper_repair_candidate_cli <task_id> --presentation-reflow`，再调用普通 `POST /modeling/<task_id>/resume`。它只有一次 `presentation_reflow_attempts` 预算，只重建 Markdown、DOCX、PDF、LaTeX 和审计，不调用 provider、不替换 Writer 正文，也不能改动代码、数值、执行证据或冻结结果。PDF 视觉检查会拒绝正文中的字面 Markdown 标题；提交审计也会检查 DOCX 正文，附录 B 源程序代码中的 `#` 字面量不计入此项。

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

退回修订必须给出具体、可执行的审查意见，且每个任务最多一次：

```powershell
curl.exe -X POST http://127.0.0.1:5173/api/modeling/<task_id>/revise-modeling `
  -H "Content-Type: application/json" `
  -d '{"comment":"删除无来源的经验阈值；补齐守恒方程、单位与真实约束证据。"}'
```

若修订调用失败，`task_status.json` 是任务终态权威来源，`modeling_decision.json` 会记为 `revision_failed` 并保留审查历史；不得把旧方案批准为通过或绕过门禁。

LLM 每次远程调用前都会重新进行 Base URL 的公网 DNS/SSRF 校验。若仅出现短暂“主机无法解析”，它会进入该次调用的有界重试并在每次重试重新校验；缺失密钥、非 HTTPS/私网地址等配置错误仍会立即失败。连续失败时先检查 provider 域名在 Docker 容器内的解析与 HTTPS 连通性，不要通过关闭公网地址校验来规避问题。

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
  重新生成 `final_acceptance_report.json`，并按最终技术验收结果把 `task_status.json`
  同步为 `completed` 或 `failed`，避免正式字体/人工修复重导后 UI 仍引用旧状态。
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

### 主 Agent（Codex / Gemini Antigravity / 对话 Agent）/ 外部引导手：角色定向指导接口

运行中的任务可接收**建议性**引导。该接口适合让主 Agent（Codex / Gemini Antigravity / 当前对话 Agent）在查看题目、`modeler_plan.json`、
执行报告后，分阶段提醒 Docker 内的建模手或编程手核查具体问题；它不是越过门禁的
系统提示词覆盖接口。注入内容仍会被标记为不可信，题面契约、ModelPlan schema、受控执行
证据和最终验收继续生效。

建议使用后端端口（Docker 默认 `8000`），并明确指定接收角色：

```powershell
curl.exe -X POST http://127.0.0.1:8000/modeling/<task_id>/guidance `
  -H "Content-Type: application/json" `
  -d '{"target":"coder","purpose":"execution","source":"agent","content":"先逐项验证全部硬约束；只有可行候选才可比较目标值。用真实时序数组计算并落盘守恒残差。"}'
```

若主 Agent 已在任务创建前完成题面/附件复核，可在创建任务的 multipart 请求中预注入，
避免首轮建模过快而错过建议：

```powershell
curl.exe -X POST http://127.0.0.1:8000/modeling `
  -F "ques_all=<题目.md" `
  -F "comp_template=CHINA" `
  -F "format_output=Markdown" `
  -F "guidance_target=modeler" `
  -F "guidance_purpose=modeling" `
  -F "guidance_content=先明确全部硬约束和量纲关系；题面中的约、左右不能改写为任意数值阈值。"
```

- `target`：`coordinator`、`modeler`、`coder`、`writer` 或 `all`；`all` 会在每个角色下一次模型调用前各投递一次，通常应优先使用精确角色。
- `purpose`：`modeling`、`execution`、`review`、`recovery`，用于审计和界面提示，不改变权限。
- `source`：可标为 `agent`、`codex`、`antigravity` 或 `operator`，仅是审计元数据，**不是身份认证**。
- 每条内容最多 4000 字符，每任务最多排队 20 条；任务完成或取消后不能再注入。若服务对外暴露，应设置 `API_AUTH_TOKEN`，否则该接口与其他本机 API 一样不具备访问令牌保护。

推荐节奏是：主 Agent 先审题→创建任务时预注入 `modeler` 建议→开启建模人工门禁后审阅
`modeler_plan.json`→批准前或 Coder 运行中向 `coder` 注入“约束、诊断、结果文件”检查项→
只依据 `execution_validation_report.json`、冻结结果和预检报告判断是否继续。若方案本身错误，
停止并重新建模；不要用引导文本直接改写既有 CSV、Manifest 或冻结结果。

当需要由当前主 Agent（Codex / Gemini Antigravity / 当前会话 Agent）实际担任引导执行者，而不依赖全局环境变量时，在创建任务时加入：

```powershell
-F "require_model_review=true"
```

该任务会在 `modeler_plan.json` 写入后停在 `waiting_review`。当前主 Agent 可读取题面契约、
计划和 `modeling_decision.md`，先向 `coder` 队列写入后续执行检查项，再调用
`POST /modeling/<task_id>/approve-modeling` 继续。若计划的物理模型、硬约束或验收口径本身不成立，
不要批准；当前主 Agent 可用一次 `POST /modeling/<task_id>/revise-modeling` 写入具体退回意见，让 Modeler
重建计划后再次审查。一次修订仍不合格或调用失败时应保留现场并停止，不得通过手工改写计划、伪造结果或绕过门禁。
此模式只增加可复核暂停，不会把 Agent 或 API 调用者伪装成可信系统指令，也不会放宽两次失败后的恢复授权要求。

如果 Modeler 在创建阶段连续返回不合格计划，而任务已启用 `require_model_review=true`，Coordinator 的拆分结果会保留为检查点。当前主 Agent 可通过 `POST /modeling/<task_id>/codex-modeling` 提交符合 `ModelerToCoder` schema 的结构化 `model_plan`；后端仍会重新执行题面契约校验、保存审计产物，并回到 `waiting_review`。随后仍必须调用 `approve-modeling` 才会进入 Coder。该接口不能用于运行中、未启用人工门禁或非 Modeler 失败的任务，也不能绕过执行验证、冻结和论文门禁。

冻结后的接管使用独立的 `execution-review` 接口，不再依赖运行中 advisory guidance 恰好被模型采纳。主 Agent / 人工应优先选择 `repair` 并给出可验证的方程、量纲、约束或诊断方向；只有复算确认可接受时才 `approve`。这使“审查→定向重算→重新冻结→再次审查”成为正式链路，而不是手工篡改候选产物。

若 provider/Coder 无法完成已经批准的执行质量返修，当前 Codex 或人工操作员可以准备一个确定性 Python 候选和静态 execution evidence，再从 **backend 容器内**调用受控候选 CLI：

```powershell
docker compose exec -T backend uv run python -m app.tools.repair_candidate_cli `
  <task_id> ques2 <execution_quality_review.json中的review_id> `
  operator_candidates/ques2_repair.py operator_candidates/ques2_evidence.json
```

该入口只接受任务目录内文件，并要求 checkpoint 已处于 `quality_repair/repair_requested`，或处于一次全量验证失败后保留了同一 `review_id`、失败子题与修复计数的 `repairing` 状态；子题必须在授权的 `failed_subtasks` 中，`review_id` 必须与当前结果哈希绑定。候选只能更新当前 `quesN_*` 产物；脚本/证据、附件、checkpoint、execution manifest、冻结结果和任务状态都不能由候选直接改写。执行超时、异常、越界文件、旧证据或证据门禁失败会回滚整个任务目录并留下脱敏拒绝审计；只有后端 `record_execution_evidence` 返回可行才写入成功 hand-off。CLI 在宿主机直接调用会拒绝，且它不会自动冻结、批准质量审查或启动 Writer。推荐闭环仍是：副本复算与教师复核 → 受控候选执行 → workflow 重新做全量 execution validation/freeze → 生成新的质量报告 → 人工按新 `review_id` 审批。

任务目录会追加 `internal_guidance_audit.jsonl`，其中只记录路由、时间、长度和内容哈希，
不记录引导正文；它不会进入候选论文或支撑材料。不要在引导内容中放置 API Key、令牌或其他凭据。

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

### Writer 单章节篇幅超限与压缩完整性门禁 (WRITER_SECTION_BUDGET_EXCEEDED / WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED)
Writer 单章节篇幅预算为 12,000 字符。若单章正文清洗后超过 12,000 字符，系统会自动触发且仅触发一次无工具定向压缩（要求保留数学公式、文献引用与脚注定义、图表引用与说明、全量数值结论）；压缩后系统会严格校验要素完整性，若返回空内容或丢失标题、公式、引用、脚注定义、图片路径/说明或关键数值事实（含单数字 0/1/5 及重复频次），系统将抛出 `WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED`；若二次压缩后依然超过 12,000 字符，系统将抛出 `WRITER_SECTION_BUDGET_EXCEEDED` 明确失败并终止，坚决拒绝静默切片截断。排查时可检查该章节 Prompt 是否引入过多背景描述或冗余表格，并在重试时精炼叙述要求。

### Coder 受保护文件快照与恢复门禁 (PROTECTED_FILE_SNAPSHOT_FAILED / PROTECTED_FILE_RECOVERY_FAILED)
Coder 执行代码前后对受保护系统状态与预算文件（`checkpoint.json`、`frozen_results.json`、`evidence_failure_budget.json` 等）进行严格快照比对与原子恢复。若快照读取失败，系统抛出 `ProtectedFileSnapshotError` 立即 fail-closed 终止；若代码篡改文件且原子恢复失败，系统抛出 `ProtectedFileRecoveryError` 立即终止，严格禁止继续进入下一轮对话或重试，禁止对损坏文件建立新快照。

## 论文收尾 P0-P2 门禁与合规工具（2026-08）

当前论文链路按三层收尾：

- **P0 产物新鲜度与状态一致性**：任务先进入 `finalizing`，基础 DOCX / audit / manifest / final acceptance 任一步异常都会形成真实失败；`task_status.json` 是任务状态权威来源。PDF、DOCX 重导前会删除旧文件，避免旧产物冒充本轮结果。`export_status.json` 与 `docx_export_status.json` 分别记录 Markdown 源哈希、输出哈希和导出结果。`frozen_results.json` 在预检期间保持纯只读，等价性核验实行严格 fail-closed。
- **P1 结构与全页视觉质量**：预检会拒绝重复参考文献、非法 Markdown 表格、表题紧贴表格等结构问题；接入 `cross_modal_audit.json` 跨模态阻断检查（代码自包含、AST 解析、最优性证书矛盾、LaTeX 损坏）；`pdf_visual_check.json` 默认扫描全部页面，并把 `pdf_sha256`、`pages_checked`、`page_count` 写入报告。提交审计只接受与当前 `res.md` / `res.pdf` 哈希一致且覆盖全部页面的报告。
- **P2 论文表达与复现闭环**：后处理会为正文中缺少邻近“图1、图2……”引用的图片补入中性图号说明（附录和代码块不改、重复运行不重复插入）；人工仍须确认图号与上下文语义匹配。连续型线性规划若把小数结果直接写成“46.67件”等，会产生 `continuous_quantity_wording` 条件警告，应改写为“连续生产当量”或另建整数规划。PDF/LaTeX 代码附录使用 `\footnotesize` 等宽字体，在保持可读的前提下减少只剩少量代码的尾页。

`candidate_manifest.json` 现使用 schema `1.2`：`submission_file` 明确唯一可上传主文件（默认 `res.pdf`），并记录主产物哈希。受控支撑材料另写入 `support_materials_manifest.json` / `support_materials.zip`，按白名单、单文件/总大小与 SHA-256 打包，默认不属于主论文上传文件。引用来源追踪只校验 DOI/URL 基本格式和本地文件哈希，仍须人工查证原始来源；`similarity_ai_risk` 仅为本地可解释草稿风险提示，不是正式查重、AI 检测或抄袭判定。内部审查目录、失败尝试目录和 `latex_project/figures/` 的 sidecar 复制图片不会进入正式候选图片列表。严格技术验收仍不替代模型、推导、引用和逐页排版的人工复核。

### 辅助工具命令行用法

1. **选题评分辅助工具（`topic_scorer`）**：
   ```powershell
   cd D:\workspace\MathModelAgent\backend
   .venv\Scripts\python.exe -m app.tools.topic_scorer --help
   .venv\Scripts\python.exe -m app.tools.topic_scorer input_topics.json --output report.md
   ```
   支持题目/路线/子问分层评分、权重自动归一化、证据与翻转条件回显；输入格式异常、缺少或包含未知评分字段时确定性报错。

2. **提交合规与分层匿名审计（`submission_audit`）**：
   ```powershell
   cd D:\workspace\MathModelAgent\backend
   .venv\Scripts\python.exe -m app.tools.submission_audit --help
   .venv\Scripts\python.exe -m app.tools.submission_audit project\work_dir\<task_id>
   .venv\Scripts\python.exe -m app.tools.submission_audit --work-dir project\work_dir\<task_id> --require-official-fonts
   ```
   分层扫描 PDF、DOCX（含 `custom.xml`、批注与页眉）及候选清单文件名中的作者/学校/联系方式泄露；对损坏文件与时效性过期报告严格 fail-closed。

### 输入文件清单与接管前置检查

#### 输入清单（`input_manifest.json`）

`POST /modeling` 和 `POST /example` 创建任务时，后端会自动为所有上传/复制的数据文件生成 `input_manifest.json`，持久化到 `work_dir/<task_id>/`。清单记录每个输入文件的安全文件名、相对路径、字节大小和 SHA-256 哈希，用于后续接管校验。用户无需手动创建，由后端自动管理。

清单格式：
```json
{
  "schema_version": "mathmodel.input-manifest.v1",
  "task_id": "<task_id>",
  "created_at": "2026-08-22T10:00:00",
  "files": [
    {"name": "data.csv", "relative_path": "data.csv", "size_bytes": 1234, "sha256": "abcdef..."}
  ]
}
```

#### 任务接管（`POST /modeling/{task_id}/codex-modeling`）

当 Modeler Agent 失败（任务状态为 `failed`）时，可通过此端点提交外部建模方案（如 Codex 生成的方案）。接管需满足以下全部前置条件：

1. **任务状态**：必须为 `failed`（非 `completed`/`frozen`/`running`）；
2. **Pristine 检查**（`is_task_pristine_for_takeover`）：
   - 不存在已完成的执行阶段、变量快照、返修记录或质量复核历史；
   - 工作目录中不存在除 `input_manifest.json` 登记的输入文件和框架管理文件（`task_status.json`、`checkpoint.json`、`modeler_plan.json` 等）之外的任何文件；
   - `input_manifest.json` 必须存在且格式合法（`schema_version` 匹配、`task_id` 一致、文件路径安全——无绝对路径/`..` 遍历/Windows 保留设备名/ADS 冒号/尾随空格句点），登记文件与磁盘文件大小和 SHA-256 哈希一致；
3. **人工审核门禁**：任务必须启用 `require_model_review` 或全局 `HUMAN_MODEL_GATE_ENABLED=true`；

任何条件不满足均返回 `409 Conflict`。接管成功后任务进入 `waiting_review` 状态，等待人工审批。

调用示例（PowerShell）：
```powershell
curl.exe -X POST "http://127.0.0.1:8000/modeling/<task_id>/codex-modeling" `
  -H "Content-Type: application/json" `
  -d '{\"modeler_response\": \"<结构化建模方案文本>\", \"comment\": \"Codex 外部建模接管\"}'
```
