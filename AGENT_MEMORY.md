# AGENT_MEMORY

> 活跃事实清单：只记现状结论 + 关键锚点 + 指针；过程叙事一律在 docs/memory/ 归档（grep 检索）。
> **硬上限：主文件 ≤5,000 字符**（用户 2026-08-29 指令，严于原 10,000 规则）。

## 归档索引

- [2026-07](docs/memory/2026-07.md) —— 华数杯前史与早期工程修复
- [2026-08](docs/memory/2026-08.md) —— 更早 235 条 + 2026-08-29 压缩轮出的 08-26~08-29 全部详细条目

- 8 月交付/导出基线已轮转至 docs/memory/2026-08.md；0825/0828 族复跑须用 huashubei。

## 仓库归属与环境要点

- john0123412 个人 fork；origin 唯一可写远程；upstream jihe520 严禁任何写操作（死命令）。
- 容器名 mathmodelagent_john_*；backend 容器重建/kill 曾三次 daemon 层挂起，处置 = 人工重启
  Docker Desktop 后 `docker compose up -d backend`；本地代码执行用 local-execution 覆盖档
  （pids_limit 1024、LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS=300），标准档无 E2B key 时
  Coder 前置直接失败、不自动降级。
- LLM stealth/ox-alpha 池曾持续 429（两次有界重试即停）；reasoning_effort 管线已恢复（58d01d3）。
- 第 7 批（base-box 上架）被 jihe520 死命令封死，视为不执行。

## 待人工 / 待办

- 平台上传三件事（文件命名 / 匿名目检 / 诚信声明）；tag 动作待指令：
  `git tag -f v2026.08.24-paper-final 37391e8 && git push origin v2026.08.24-paper-final`。
- 20260828 两个低危观察待决策：5.3 节"SOC 恰好回到初始值"与数据不符；全篇无论文献区。

## v23 算电协同·去伪造重建（2026-09-02 落地，task=20260830-234433-4b3226317d54a94062be7a3379cf1a10）

- **真值与血统（已被 09-02~09-03 多轮更新覆盖）**：notebook 4 code cell 全真实执行；Q4 曾因
  `scenario_objective_range` 方向写反误报，修后 100 样本真实达标；frozen/manifest 走
  rebind→hash 重算受控刷新。当前冻结数字以 09-03 终态为准（MC 均值 1,284,013,383）。
- **Q4 争议已消解（09-02 17:00 轮）**：原 Q4 失败是 `scenario_objective_range` **约束方向写
  反**（写成 `lte 0.5`，实为 `gte 0.05`），不是模型不行。修 `lp_core.py`/`q4_model.py` 后按
  **100 样本真实重算**（q4_rerun5）：非支配 6≥5、CI 0.0457≤0.05、一致性 6.1e-05≤0.01、
  区分度 0.7408≥0.05、MC 成本均值 1,284,013,383 —— **四个目标全部真实达标，无需放宽**。
  res.md 由 `align_resmd_q4_v2.py` 同步到 100 样本数值（0.0597→0.0457 等）。
- **全门禁已绿（09-02 19:44）**：`final_acceptance=TECHNICAL_PASS`（12/12 项通过）、
  `submission_audit=PASS`（14/14）、`preflight=PASS`、`pdf_visual=PASS`、`cross_modal=PASS`、
  `execution_validation_report=PASS`。res.pdf 68 页（正文 30 ≤ 上限 30，附录 27 页为完整源码）、
  res.docx 2.79MB。三项原 FAIL（`submission_audit` 陈旧 / `artifact_freshness` /
  `complete_source_appendix`）已清零。
- 复用脚本：`internal/audit_20260901/{q4_model.py, lp_core.py, patch_q4_cell.py,
  rebind_manifest.py, run_gates.py, draw_q4_ci.py, align_resmd_q4_v2.py, trim_abstract.py,
  compress_resmd2.py, regen_pdf.py, **fix_appendix.py, fix_support_caption.py,
  reconcile_gates2.py**}`。复用原则：任务级脚本只放 work_dir 内部审计子目录（见 AGENTS.md
  工作区防污染铁律）。详细过程见 `.workbuddy-ai/memory/2026-09-02.md`。
- [09-02 第五~七轮+09-03 精修轮] P0-P3收敛、摘要5段、提示词/编辑政策治本；审计修复（11孤立
  引用删、9悬空内嵌、Mavrotas{[6]}→[9]、6.2→6.3、AI审计24.5→约21）；外审86-89→四项语义对齐
  （Q2统一λ扫描+对偶定价+真实支配检验{lam0,lam1500}、Q3披露循环约束1.5次/日+敏感性、Q4降格
  固定迁移再优化、CI拆分±4.57%、关键词五项、7.2真实局限）。终态PDF 72页正文30、TECHNICAL_PASS
  12/12、五件哈希MATCH。陷阱：append_code_appendix 必跟 fix_support_caption.py。
  详文 docs/memory/2026-09.md。

## Agent 调用 Docker 后端路线图（2026-09-03，PR #40）

- **目标**：外层 Agent 稳定调用本机 Docker 后端（`docker compose up` 仅 backend+redis，前端 `--profile frontend` 可选），0.0.15 规则进入实际执行链而非仅 `skills/`。
- **批 A**：`writer 600-900字4段 / 11pt1.3 / 30页+摘要单页` 收敛至 profile；手机号漏检等通用修复；`docker-compose.yml` 去 `5173/api` 耦合、`frontend` 加 profile、`common_router` 增 `deployment`、`task_client` 基址切 `8000`。
- **批 B**：`task_client.py` 薄客户端（`doctor/submit/inspect/events/guide/approve-model/revise-model/review-results/resume/cancel/artifacts/repair-*`）+ 后端 `Idempotency-Key/GET /tasks/{id}/events/artifacts` 与 `guidance_id` 回执（`accepted/consumed`）。
- **批 C**：`task_budget.json` 累计预算（调用/known token/运行时长）持久化、未知 usage 标 `unknown`、`_finalize` 备份保留+`to_thread` 防阻塞、`cancel` 保留停止证据。
- **批 D**：`backend/app/resources/modeling_guides/{01-05}.md`（确定性基线/硬约束/统计严谨/Pareto/溯源）按诊断 profile 加载；`paper_review` 六维评审材料包+版本绑定（`manuscript_sha256/frozen_result_id/artifact_set_id`）+ 五类分流。
- **批 E**：`figure_plan` 路由（data/template/diagram/physical）+ 多面板+追溯校验；`doctor` 容器体检与模板能力表（`huawei→huaweibei` 别名，后端仅 4 profile）。
- **批 F**：`test_agent_docker_backend.py` 10 项契约验收 + 轻量 LP 烟雾题 + 完整链路哈希核对；`STARTUP.md` 增 Agent 调用手册。
- 取证：`mathmodel_workspace_0.0.15 (323 MB)`；验证：`task_client doctor` + `docker compose config` + `unittest` 10/10。

- [09-03 LNS升级实测→不采纳] v2 LNS全链本机跑通（MILP 22s/次、单算子7候选0违反），但缝合验证
  判死：LNS自口径改进−0.4%，跨当前 lp_core+份额口径 1833.7M > 贪心λ点 1440.1M（anchor vs share
  口径差27%不可通约）。强行缝合=新造假链。决策：保留88-90全绿交付态，LNS产物留v2目录不进主链；
  快照未动；"聚合近似"扣分如实保留在论文7.2。
- [09-03 LNS终局] milp options"threads"致Not Set（已修）；share口径负优化−0.07%+GPU违反2→242，
  双重证伪终结。
- [09-03 优化轮] Q1基线对照（朴素72.86 vs GBR 54.99，+24.53%，notebook补Q1 cell）；6.1.1重写
  真实OAT+表6弹性；表号1-8重排、空6.2删、6.3并7.2、关键词标准词。终态74页正文30全绿。
- [2026-09-03] LP fdd491（完整 ID 见归档）已 completed / TECHNICAL_PASS；default 预检条件项、审计 WARN 仍需复核。外审发现正文数值/图文/排版问题，保留现稿待受控返修。7 cell 新内核重跑、3 表 MATCH；详 docs/memory/2026-09.md。
- [2026-09-04] PR #40 已合并 main（merge 68cb89d）：批 A-F+P1/P2+P2 边界（default 条件放行限定显式 profile、失败 sensitivity 不向 Writer 传数值/图、paper_review 三版本写前校验）+finalize 失败清理半成品 manifest+旧断言同步批 A 契约；CI 全量 905 项转绿（此前分支 CI 一直失败）。
