# MathModelAgent 项目规则

## Agent 接手顺序

新 agent 接手时必须先读：

1. `AGENT_MEMORY.md`
2. `AGENTS.md`
3. 按任务需要再读 `STARTUP.md`、`docs/md/CUMCM2026模板替换指南.md`、`docs/md/PDF模板导出说明.md`

不要一上来全盘搜索仓库；不要扫描 `.venv/`、`frontend/node_modules/`、`backend/project/work_dir/` 的历史任务，除非用户明确要求。

## 核心原则

- 默认在仓库根目录 `D:\workspace\MathModelAgent` 内工作。
- 修改前先看 `git status --short --branch`，避免覆盖用户或其他 agent 的改动。
- 不要读取、打印、提交或写入真实 API Key、token、cookie、私钥正文，除非用户明确要求；只可提变量名和配置路径。
- 不要擅自提交、推送、合并、删分支或清理 worktree，除非用户明确要求。
- 验证结论必须基于实际运行结果；未运行就明确写“未验证”。

## 任务脚本与临时文件存放规范（工作区防污染铁律）

- **任务级脚本隔离**：所有针对具体建模任务的独立求解脚本（`*_solver.py`）、数据清洗脚本、绘图重绘脚本、草稿文件，**必须且只能保存在对应的任务目录 `backend/project/work_dir/<task_id>/` 下**。
  - 严禁向仓库根目录、`scripts/` 目录或 `backend/` 源码目录写入任务级脚本。
  - 任务目录下的 `.py` 脚本会被论文后处理器自动提取为附录源程序，并自动打包进 `support_materials.zip`；且因 `work_dir` 处于 Git 忽略状态，绝不会污染仓库。
- **一次性调试脚本**：仅供一次性排查/测试的临时代码，必须保存在 IDE 的 `scratch/` 目录或临时目录中，不得散落在仓库代码树内。
- **`scripts/` 目录范围**：`scripts/` 目录仅限存放经过 Code Review 的全项目通用运维/部署脚本（如 `docker-local-execution.ps1`）。严禁在此创建临时测试或绘图脚本。
- **Python 执行环境固定**：执行 Python 代码时，必须使用固定的虚拟环境（Windows 本地使用 `backend\.venv\Scripts\python.exe`，Docker 容器使用 `docker compose exec backend uv run python`），严禁使用系统全局 Python。
- **Git 状态自检**：每次修改或汇报前必须执行 `git status --short --branch`，确保工作区无未预期的 `?? scripts/` 或根目录未跟踪文件。


## 任务收尾与记忆同步

每次完成功能修复、风险修复、导出链路调整、模板调整、验证流程调整后，提交前必须检查是否需要同步更新以下文件：

1. `AGENT_MEMORY.md`
2. `STARTUP.md`
3. `docs/md/PDF模板导出说明.md`
4. `docs/md/CUMCM2026模板替换指南.md`
5. `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
6. `backend/app/templates/export_profiles/README.md`

判断标准：

- 改变主交付链路、默认 profile、导出行为、验证命令、已知风险、失败诊断顺序，必须更新 `AGENT_MEMORY.md`。
- 改变用户使用方式、启动方式、命令、Docker/Windows 导出路径，必须更新 `STARTUP.md`。
- 改变 PDF/DOCX/LaTeX 导出行为、字体 fallback、模板路径或验收标准，必须更新 `docs/md/PDF模板导出说明.md`。
- 涉及 `cumcm2026` 模板、官方模板替换路径、DOCX reference、LaTeX 模板资源，必须更新 `docs/md/CUMCM2026模板替换指南.md`。
- 改变最终人工复核口径，必须更新 `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`。
- 修改 `backend/app/templates/export_profiles/` 资源结构，必须更新 `backend/app/templates/export_profiles/README.md`。

如果判断不需要更新说明文件，最终汇报也必须说明：“已检查说明文件同步需求：无需更新，原因是……”

每次提交前的汇报必须包含：

- 代码改动文件。
- 文档/记忆文件是否已同步。
- 未同步的理由。
- 验证命令和结果。

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

## 主 Agent（Codex / Gemini Antigravity / 当前对话 Agent）可执行的人工复核补充门禁

当用户要求验收论文、修复论文/结果链路，或明确授权主 Agent（无论当前宿主环境为 Codex、Gemini Antigravity、Claude Code 或其他交互式 Agent 客户端）代为执行可机检的人工复核时，不能只报告自动门禁 PASS；必须在资源允许范围内完成并记录下列操作：

1. **源码干净重跑**：在隔离副本中用新内核按 notebook/脚本顺序执行；不得依赖 notebook 的历史输出或已有变量。发现语法错误、未定义变量、顺序依赖或与正文矛盾的输出时，先修正源码，再在正式任务目录重跑，并重新登记执行证据、冻结结果和导出产物。
2. **独立数学核验**：对关键结论使用代数推导、顶点枚举、另一实现或结果表交叉复算。检查解是否可行、约束是否满足、目标值/量纲/敏感性结论是否一致；不得只因求解器 `success` 就宣称数学正确。
3. **引用真实性核验**：正文存在外部引用、软件/算法说明或数据来源时，在线打开优先的官方页、原始论文或权威数据源，核对其真实可访问且能支撑对应表述；若全文没有外部引用，明确记录“无外部引用可核验”，不要伪造文献。
4. **链路重建与哈希复核**：源码或结果有改动时，必须通过受控 `record_execution_evidence` / 冻结流程刷新来源哈希，重新生成 Markdown、DOCX、LaTeX sidecar 和 PDF，并检查 execution validation、preflight、语义版式、PDF visual、submission audit、candidate manifest 的当前状态与主产物哈希。

上述步骤是主 Agent 能实际执行的技术复核，不能冒充提交人已完成的事项。文件命名、提交平台规则、竞赛匿名/诚信声明和最终主观排版确认仍由用户或指定队员负责；最终汇报必须明确区分已执行和待人工确认的项目。

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

## 多智能体 Subagent 调用限制（通用 Harness 约束）

在各类 Agent Harness（包括 Codex、Gemini Antigravity、Claude Code 等）中，主 agent 发起子任务或 subagent 必须遵守以下通用隔离与预算限制：

- 主 agent 发起子任务时必须显式传入 `fork_context:false`（或关闭上下文深拷贝）；严禁传入 `fork_context:true`，确保子 agent 不继承无界父线程上下文。
- 只有主 agent 可以调用 `spawn_agent`（或 `Agent` 工具）。任何 subagent 均不得再创建 subagent、不得形成嵌套任务树；需要继续拆分时，subagent 应把建议和阶段摘要返回主 agent。
- 同一时刻活动的直接 subagent 最多 5 个；各工作流阶段默认仍由主线程串行执行，只有互不依赖的旁路任务才可并行，且不得为加速而无边界拆分。
- 子 agent 的任务说明只提供阶段性摘要、明确目标和文件路径；不得回灌整段工具输出、完整父对话或与本任务无关的上下文。
- 真实建模任务如需断点续传，优先走后端 `POST /modeling`；其工作流具备 checkpoint 与局部回修能力。
- 发起多智能体调用前，确认当前账户或代理具备经用户授权的隔离计费与预算限制；未确认时不得 spawn。

## 赛前协作与恢复规程

本节将赛前协作要求绑定到现有导出、人工门禁、记忆和验收机制；其优先级低于上文的安全限制与用户明确指令。

### 交付优先与 Baseline

- 修改建模、导出或验收链路时，先保留一条经验证能产出 `res.md`、`res.json` 和 `res.docx` 的最小路径；格式和算法优化必须在该路径可复现后进行。
- 对同一故障完成一次有证据的排查后仍不能恢复时，停止扩大改动面。导出问题优先使用已验证的 `export_profile=default` 或成功的旧配置产生可交付结果，再单独追踪根因。
- `cumcm2026` 是赛前 Baseline，不把猜测的官方格式变更写进模板。官方模板更新只按 `docs/md/CUMCM2026模板替换指南.md` 替换并完成回归验证。
- 赛前由项目负责人指定每周官方模板检查人和记录位置；未指定前，检查结论记录在 `AGENT_MEMORY.md` 的验证条目中，且不得对模板作预防性改写。

### 人工决策与验收边界

- 开启 `HUMAN_MODEL_GATE_ENABLED=true` 后，`modeling_decision.md/json` 必须由赛前已指定的主审批人或备用审批人实际审阅后 approve。未明确两人时，不得将人工门禁作为比赛当天唯一流程。
- `/status` 的 `feature_warnings` 如指出通用 HIL、`FALLBACK_ENABLED` 等能力未接入主工作流，赛时不得把它们当作应急路径。可依赖的路径限于已验证的人工审批、手动切换运行时模型配置和已验证的导出 profile。
- `paper_preflight_report.json`、`pdf_visual_check.json` 和 `submission_audit_report.json` 的 `PASS` 仅说明对应技术门禁通过。提交前仍须由队员复核建模假设、数学推导、关键数值、引用和 PDF/DOCX 排版。
- 禁止在规则、提交、日志或聊天中写入备用凭据正文；赛前将主/备 provider 的变量名、保管人和验证日期登记在项目外部的安全记录中。

### 故障记录与恢复日

- 真实任务、真实 provider 调用或正式导出出现失败、`FAIL`、`CONDITIONAL_PASS` 时，在修复或重试前向 `AGENT_MEMORY.md` 追加：`- [日期] [现象] [触发条件] [当前处置 / 是否已修复]`。单测中的预期失败无需登记。
- 同一任务或功能连续两次失败后，停止增加新方案或重复提交相同请求，并依次执行：
  1. 记录失败并检查 `AGENT_MEMORY.md` 的已知风险；
  2. 由赛前指定的决策人手动切换到已验证的备用 provider 配置，最多再尝试一次；不得依赖 `FALLBACK_ENABLED` 自动切换；
  3. 仍失败则回退到已验证的 profile 或旧配置，优先生成可交付产物；
  4. 停止未验证的大改动，整理复现条件、已有产物和下一步排查问题。
- 赛前必须完成一次完整长度历年题端到端验收，不能仅使用本文件中的线性规划烟雾题；验收记录须包含 preflight、PDF 视觉检查、LaTeX sidecar 和人工复核结论。
- 赛前必须演练一次上述恢复流程，例如人为中断 provider 或制造 preflight `FAIL`；演练以无需改代码也能回退到可交付路径为通过条件。
