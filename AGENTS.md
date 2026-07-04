# MathModelAgent 项目规则

## 核心原则

- 默认在仓库根目录 `D:\workspace\MathModelAgent` 内工作。
- 修改前先看 `git status --short --branch`，避免覆盖用户或其他 agent 的改动。
- 不要读取、打印、提交或写入真实 API Key、token、cookie、私钥正文；只可提变量名和配置路径。
- 不要擅自提交、推送、合并、删分支或清理 worktree，除非用户明确要求。
- 验证结论必须基于实际运行结果；未运行就明确写“未验证”。

## 前端本机 Node 工具链硬限制

在 Windows 本机环境中，agent 不得主动运行任何会调用本地 `frontend/node_modules`、安装前端依赖、启动本地前端构建或检查的命令，包括但不限于：

- `pnpm i` / `pnpm install`
- `npm install` / `yarn install`
- `pnpm run dev`
- `pnpm run build`
- `pnpm exec vue-tsc` / `vue-tsc`
- `pnpm exec vite build` / `vite build`
- `frontend\node_modules\.bin\biome.cmd`
- `pnpm exec biome` / `npx biome`
- `node_modules\.bin\*`

原因：当前 Windows 环境曾出现前端工具链异常派生大量 `node.exe`，导致系统卡死。

如确实必须验证前端：

- 优先使用 Docker Compose 已运行的前端服务 `http://127.0.0.1:5173` 做浏览器/接口级验证。
- 或由用户手动运行前端命令后回传结果。
- 如用户明确授权 agent 运行本机前端命令，必须先说明风险、限定一次命令、设置短超时，并在执行后检查是否残留异常 `node.exe`。

## 允许优先使用的验证方式

后端验证优先使用以下方式：

```powershell
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\python.exe -m unittest app.tests.test_scholar_search app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
.venv\Scripts\python.exe -m ruff check app
```

Docker 验证优先使用以下方式：

```powershell
cd D:\workspace\MathModelAgent
docker compose up --build -d
docker compose ps
curl.exe http://127.0.0.1:8000/docs
curl.exe http://127.0.0.1:5173/
docker compose exec backend uv run python -m unittest app.tests.test_scholar_search app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
docker compose exec backend uv run python -m ruff check app
```

读取日志时默认限制输出量：

```powershell
docker compose logs backend --tail=200
```

需要排查时最多扩大到 `--tail=2000`，不要持续 `follow` 日志。

## Docker 真实案例验收

重建 Docker 后，如用户要求真实案例测试，优先选择轻量题目，避免长时间大模型任务：

```text
某工厂生产 A、B 两种产品。
A 需要 2 小时机器时间、1 小时人工时间，利润 40 元；
B 需要 1 小时机器时间、2 小时人工时间，利润 30 元；
机器时间最多 100 小时，人工时间最多 80 小时。
求最优生产方案，并分析机器时间增加 10 小时时利润变化。
```

验收重点：

- `/tasks` 中对应任务为 `completed`。
- 工作目录存在 `res.md`、`res.json`、`res.docx`、`candidate_manifest.json`。
- 续传相关任务存在 `checkpoint.json`、`variable_snapshot.pkl`、`variable_snapshot_meta.json`。
- 后端日志出现变量快照恢复或增量重放相关信息，例如 `变量快照已恢复`、`快照后增量重放`。
- Docker 镜像已装 `pandoc`/`xelatex`/TeX Live，PDF/LaTeX sidecar 默认应能生成；官方字体（Times New Roman/SimSun 等）缺失时会自动 fallback 到开源等效字体（Liberation/Noto CJK/AR PL KaitiM GB），不影响任务成功。如果容器环境异常导致 PDF/LaTeX sidecar 仍被跳过，只要 Markdown/Word/JSON 成功且任务状态为 `completed`，不视为主流程失败；正式提交前建议改用 Windows 本地导出（`backend/app/tools/export_cli.py`，见 STARTUP.md）用真实系统字体重新生成一次。

## 文献搜索与 Tavily

- Writer 的 `search_papers` 工具现在是多源聚合：OpenAlex、Semantic Scholar、Crossref、arXiv，外加可选 Tavily。
- `OPENALEX_EMAIL` 未配置时只跳过 OpenAlex，不禁用文献搜索。
- Tavily 只在 `TAVILY_API_KEY` 存在且 `SEARCH_ENABLED=true` 时启用，用于网页、官方报告和数据来源补充，不替代学术数据库。
- 需要用本机系统环境变量测试 Tavily 时，只检查变量是否存在，不打印 key 原文；测试输出只展示结果标题、来源和类型。
- 若工具指定 `source_types=["web"]`，只请求 Tavily，避免额外触发学术源限流。

## 资源限制

- 默认串行执行命令，不开高并发。
- 单测默认 1 worker，最多 2 worker。
- 不要启动多个浏览器实例；需要 UI 验证时只使用一个页面。
- 命令卡住或连续失败后停止排查并汇报，不要无限重试。
