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
  3 个含明文 emooo key 的 tmp_*.py 一并消失（key 已由用户轮换，2026-08-30 确认，风险关闭）。
- **重跑战役 v3-v14（08-29~30，12 轮，agnes flash）**：死因逐轮确诊并修复——证据 id 三处
  一致（自动绑定）、零解断言、pivot 字典方向、数据地基自检、ques3 LP 新能源项口径（等式漏
  新能源项→残差=新能源量级）、pro 模型 key 无权限、XGBoost 未装→sklearn GBR+滞后特征、
  容器被并行 compose up 重建（ExitCode=0 非 OOM）后"本轮未更新"拒证据。**v8/v9 证明
  ques1/2 可真实通过**（RMSE 90.76≤120、R² 0.346≥0）；v10 起注入 LP/预测逐字模板于
  tmp/renun_20260829/。**当前墙：08-30 12:10 起容器到 Cloudflare 网段（apihub/1.1.1.1）
  Errno 101/timeout，宿主机 200 正常，backend 与 Docker Desktop 重启均无效（pypi/百度可达）**
  ——疑宿主防火墙/安全软件拦 Docker NAT 流量，待用户处置（或提供本地代理端口设
  LLM_OUTBOUND_PROXY）。恢复后一键重启 v15：创建→waiting_review→注入 id 表+模板→批准。

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

- 平台上传三件事（文件命名 / 匿名目检 / 诚信声明）；tag 动作待指令：
  `git tag -f v2026.08.24-paper-final 37391e8 && git push origin v2026.08.24-paper-final`。
- 20260828 两个低危观察待决策：5.3 节"SOC 恰好回到初始值"与数据不符；全篇无论文献区。
