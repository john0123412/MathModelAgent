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

## 当前隔离实验（未纳入冻结交付）

- [2026-08-25] Q2 Phase A 在 `20260825-phasea-q2-v2-recovered/` 按官方 `GPU_Demand×overlap` 重建同口径基线并独立 PASS；A1a 释放 1,000 任务的联合 MILP 三锚点均 `optimal/gap=0`，两个可复核锚点把固定参考点 HV 从 0.107084 提至 0.166635 并支配旧候选，见 `phase_a1/a1a_gate_analysis.json`。
- [2026-08-25] A1b 因两次未形成完整可恢复候选池而 STOP：多算子池、epsilon 池和确定性复跑未完成，Phase A 总门禁 FAIL，不进入 C/B、不刷新冻结链；原沙盒删除与复跑细节见 `RECOVERY.md`、`phase_a1/A1B_STOP_HANDOFF.md`。

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

- [2026-08-26] **Phase C/B 收尾完成：Q2 v2（五算子 LNS/MILP）替换版在新目录通过全套导出验收**：
  1. 任务目录 20260825-phasec-replace-v2：合格池 35（剔除 v2_baseline__ 与超时算子）→ 非支配 23 点；代表膝点 gpu_peak_pressure__anchor_carbon（门禁指定；垂距规则交叉核选相邻候选 eps_latency_25，两候选均落表，差异已记录不静默）；LP 独立复算 cost=1,905,939,325.34/carbon=2,079,325.83 与池值一致，功率残差 5.68e-14；迁移 8,935 次（修复 8,514+LNS 421）；GPU_Demand×overlap 官方口径已写入 audit/evidence/正文。
  2. frozen_results.json 手工更新 5 个 sources 哈希 + 8 个 ques2 指标值；execution_validation.json 经 record_execution_evidence 受控重绑（validation=PASS）。res.md 十二处 Q2 同步（含表3 新端点 marginal_cost__anchor_cost/latency_reduction__anchor_latency、421/8,935、overlap 口径、膝点交叉核验声明）；res.json 为历史 Writer 恢复草稿（含更旧数值），未篡改该 provenance，仅登记说明。
  3. task-refresh(profile=huashubei 照抄 task_request) 全绿：execution_validation/preflight/pdf_visual/submission_audit=PASS+TECHNICAL_PASS；candidate_manifest artifact_hashes 5/5 MATCH、submission_file res.pdf 哈希一致；PyMuPDF 抽核 146 页新值全命中、旧值/旧名零残留。表6 宽表条件门禁两轮收敛（167→121→阈值 120 以下），根因为门禁源码 max_line_length>=120。
  4. 旧目录一致性：文件数 204=204；主控快照 tmp/pre_replace_snapshot_C.txt 哈希 dd4737... 的 recipe 未提供，11 种标准 recipe 均未复现——按熔断停止猜测；我方文档化 recipe（排序 relpath+"sha256␣␣"+LF 连接）复算哈希 85a01385780ab0a45707...，供主控用其原 recipe 比对；本会话全部写入仅限新目录。
  5. 已知边界：附录代码清单仍为冻结 v1 q2_energy_aware_solver.py，v2 产物的生成管线脚本位于 recovered/phase_a1（q2_lns_a1b_*.py）未入附录清单——provenance 归属待主控定夺；Q4 冻结数值基于旧代表调度，4.4.1 已更新指针名称，Q4 是否需随新调度重跑由主控决策。

- [2026-08-26] **代码块样式 + v2 终稿收尾**：① 导出链路代码块统一"白底+浅灰边框+左行号"
  （export_profiles.py / tex_project_exporter.py×4 / gmcmthesis.cls，含删除上游原有底纹）；
  ② **最终交付 = work_dir/20260825-phasec-replace-v2/**：res.pdf 146 页（新值全命中）+
  submission_body.pdf 重切 22 页（internal/build_submission_body.py，clip 止于[10]，
  新值命中/零 S1_cost_P2）；旧目录 20260823-040225 已被 v2 取代仅作存档；
  ③ 原版四件交付物备份在 tmp/backup_res_pdf_precodestyle_20260826/（SHA256SUMS_before.txt）。
