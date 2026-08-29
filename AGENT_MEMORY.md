# AGENT_MEMORY

> 活跃事实清单：只记现状结论 + 关键锚点 + 指针；过程叙事一律在 docs/memory/ 归档（grep 检索）。
> **硬上限：主文件 ≤5,000 字符**（用户 2026-08-29 指令，严于原 10,000 规则）。

## 归档索引

- [2026-07](docs/memory/2026-07.md) —— 华数杯前史与早期工程修复
- [2026-08](docs/memory/2026-08.md) —— 更早 235 条 + 2026-08-29 压缩轮出的 08-26~08-29 全部详细条目

## 正式交付与任务现状（2026-08-29 深夜）

- **正式交付 = work_dir/20260825-phasec-replace-v2/**：res.pdf 235 页 + submission_body 22 页，
  四门禁全绿 + TECHNICAL_PASS（Q2 v2 五算子 LNS/MILP）。v1 冻结稿 20260823-040225（145 页）
  与 tmp/backup_frozen_task_20260824 仅作存档回退。
- work_dir 清理定案（f607cca，经用户指令）：保留 5 目录 = 20260817-163525、20260823-040225、
  20260825-phasec-replace-v2、20260828-080924、backup_frozen_task_20260824（851MB→263MB）。
- 20260828-080924 论文被**质量否决**（方法-正文不一致，不得作提交候选；completed 仅代表
  门禁算术一致），处置记录在其 internal/DISPOSITION_20260829.md。
- 该任务 scratch/root_scripts_20260828/ **仅剩 MANIFEST.md**：32 个 backend 根目录一次性脚本
  08-29 23:03 被并行清理删除、工作区无副本（本文件旧条目"保留归档脚本"作废，以本条为准）；
  3 个含明文 emooo key 的 tmp_*.py 一并消失，**key 仍待轮换**。
- **活跃任务 20260829-151338-f3652c56（2026 华数杯 C 题重跑）**：Modeler 完成（checkpoint
  23:15）；23:24 曾因缺 E2B_API_KEY resume 失败；23:33 并行会话以
  docker-compose.local-execution.yml 重建 backend（CODE_INTERPRETER_KIND=local、
  ALLOW_LOCAL_CODE_EXECUTION=true，E2B_API_KEY 仍缺），23:34 resume 进入 Coder，本地解释器
  执行正常（迭代自修复中）。本任务同时验证 114b938 Writer 修复后的 resume→导出全链路；
  终态以 task_status.json 与门禁报告为准。
- **上任务终态（08-29 深夜）**：ques1 真实通过（RMSE 5.40≤10、R²_test 0.333 如实偏低）；
  ques2 初版 pivot 字典方向 bug 全零→execution-review 打回修复（基线 1.8B 真实，ε 前沿仅
  2 点且一点=基线）；ques3 仍零解（储能零充放、5/6 区域基线丢失），质量返修预算每任务
  一次已耗尽（409），任务停于 waiting_quality_review（review_id 3a38c70d…），拒绝批准零解
  进 Writer。教训：机器质量筛查查不出全零退化解；返修预算应留给最重子题。
- **v4 重跑已发起（08-29 深夜，同一题面/附件/huashubei/require_model_review）**：预注入
  全部确诊 bug 模式（列名清单/字典方向/区域自检/零解断言/跨问基线一致/ε 单调/禁硬编码）。
  .env.dev 已回退 agnes-2.5-flash @ apihub.agnes-ai.com/v1（用户供 key，仅存 gitignored
  .env.dev）。
- **v4 终态（failed，已停止自动重试）**：Modeler 计划合格并批准；ques1 证据 3 次被拒
  （metrics 值 538.0/144.0 无法在绑定 source_path 中复查）→ 注入绑定修复引导 resume →
  熔断器 PLAN_CONFLICT 立即触发（evidence_failure_budget 跨 resume 持久化，须修正计划）。
  结论：三轮自动运行（20260828 原始、v3、v4）均止于不同门禁，唯一走完全程的是 v1
  （→v2 交付）。若再战 v5：必须在 ModelPlan 层面规定验收表格式（每指标值写入
  acceptance CSV 并绑定自身路径），并把 revise-modeling 预算留给计划层修正。

## 门禁与导出基线（a1beddf，2026-08-29 入库）

- huashubei profile：0.6cm 边距 / +20pt 右余量 / 35 页上限 / 关键词任意页 / claim_trace≤20
  不阻断（pdf_visual_checker.py HUASHUBEI_* 常量+条件分支）；cumcm2025/2026 = 2.5cm、20 页、
  首页关键词、claim_trace 严格；default = 2.0cm；export_cli 接受 CONDITIONAL_PASS（硬 FAIL 仍拒）。
  **复跑 0825/0828 族任务必须 profile=huashubei，否则按严格基线卡。**
- 全量回归口径：backend 下 `python -m unittest discover app/tests` 888 OK (skipped=2) +
  `ruff check app` 全绿；跨 worktree 验收必须"待测代码树 + 原生 venv"。

## 仓库归属与环境要点

- john0123412 个人 fork；origin 唯一可写远程；upstream jihe520 严禁任何写操作（死命令）。
- 容器名 mathmodelagent_john_*；backend 容器重建/kill 曾三次 daemon 层挂起，处置 = 人工重启
  Docker Desktop 后 `docker compose up -d backend`；本地代码执行用 local-execution 覆盖档
  （pids_limit 1024、LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS=300），标准档无 E2B key 时
  Coder 前置直接失败、不自动降级。
- LLM stealth/ox-alpha 池曾持续 429（两次有界重试即停）；reasoning_effort 管线已恢复（58d01d3）。
- 第 7 批（base-box 上架）被 jihe520 死命令封死，视为不执行。

## 待人工 / 待办

- emooo 中转站 key 轮换（明文曾入已删 tmp_*.py，key 本体仍有效）。
- 平台上传三件事（文件命名 / 匿名目检 / 诚信声明）；tag 动作待指令：
  `git tag -f v2026.08.24-paper-final 37391e8 && git push origin v2026.08.24-paper-final`。
- 20260828 两个低危观察待决策：5.3 节"SOC 恰好回到初始值"与数据不符；全篇无论文献区。
