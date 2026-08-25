# AGENT_MEMORY

> 本文件是接手必读的**活跃事实清单**，不是过程日志。
> **硬性上限：总字符数 ≤10,000**（`wc -m AGENT_MEMORY.md` 实测）。超限时把最旧条目移入
> `docs/memory/2026-MM.md` 归档（该月无归档则创建）。条目模板：一行结论 + 关键数字/SHA/路径锚点
> + 指针；**过程叙事直接写归档，不进本文件**。历史细节对归档目录全文 grep 检索。

## 归档索引

- [2026-07](docs/memory/2026-07.md) —— 华数杯前史与早期工程修复
- [2026-08](docs/memory/2026-08.md) —— 竞赛任务全过程取证记录、改进方案 1–6 批执行明细

## 项目终态（2026-08-25 封版）

- 华数杯论文冻结 @ origin/main=37391e8：`res.pdf` 145 页 + `submission_body.pdf` 22 页，位于
  `backend/project/work_dir/20260823-040225-2f42da7fd77c865ebc61480579163b07/`；六门禁全绿 +
  TECHNICAL_PASS；评审终轮 11 项 PASS、定级 92–93。回退路径：`tmp/backup_frozen_task_20260824` + 沙盒。
- 待人工项：平台上传三件事（文件命名 / 匿名目检 / 诚信声明）。
- 待用户指令的 tag 动作：`git tag -f v2026.08.24-paper-final 37391e8 && git push origin v2026.08.24-paper-final`
  （当前 tag 仍锚在措辞修正前的 48a0e69）。技术侧不再改动任何算法、数据、图或正文。

## 仓库归属与 main 历史锚点

- 本仓库为 john0123412 个人使用 fork；origin 是唯一可写远程；upstream jihe520 仅参照，
  对其任何仓库（含 base-box）严禁写操作（死命令永久生效）——详见 CLAUDE.md/AGENTS.md「仓库归属与操作边界」。
- main 链：b51910d → #37(74be477 改进方案1–6批) → #38(a988df2 合并后验收修复) → 活任务收口
  (4b69513/58d01d3/37391e8) → #39(2e1a1b7 归属口径固化)。
- Docker 容器名已改 `mathmodelagent_john_*`；下次 `docker compose up` 会重建容器，属预期。

## 已知风险与环境要点

- Docker Desktop：backend 容器重建/kill 曾连续三次 daemon 层挂起（疑受 LLM_REQUEST_TIMEOUT_SECONDS=1800
  影响），处置=人工重启 Docker Desktop 后 `docker compose up -d backend`；宿主机 venv 全功能可用。
- LLM stealth/ox-alpha 共享池曾持续 429（两次有界重试即停，勿无限重试）；glm-5.2:free 探测可用；
  reasoning_effort 管线已恢复（58d01d3，禁思考语义优先于 effort 透传）。
- `.claude/hook_lint.sh` 在 worktree 下路径假设失效（找 `./venv`），backend py 编辑会报 hook 错但
  编辑已生效——既有问题待修。
- 跨 worktree 验收铁律：unittest discover 导入跟随 cwd，必须以"待测代码树 + 原生 venv"组合执行。
- 全量回归口径：backend 目录下 `python -m unittest discover app/tests` ≈879 tests OK (skipped=2)
  + `ruff check app` 全绿。

## 工程沉淀指针

- 综合改进方案第 1–6 批全部落地（PR #37/#38/#39）；方案文档
  `D:\Users\Johnny\downloads\mathmodel-re\consolidated-improvement-plan.md` 已标完成态。
- 第 7 批（base-box 市场上架）已被 jihe520 死命令封死，除非用户提供自有分发目标并当次授权，视为不执行。
