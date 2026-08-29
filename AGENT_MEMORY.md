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

- [2026-08-26] **终稿复核轮（引用/AI 声明/排版三整改）**：① 参考文献净化：摘除 [9]/[10] AI 工具条目，
  8 条文献经 Crossref/doi.org/OpenLibrary/SJTU 原文页逐一核实为真实（[4]=ICAC'14 GreenWorks）；
  ② AI 使用声明独立成节置于参考文献之后（结论章旧声明+附录C 迁移合并）：
  ensure_huashubei_ai_disclosure 重写（幂等出口+围栏声明头自愈前置）、_check_ai_disclosure 新契约、
  normalize_chinese_references 与 references/reference_format 两处分区改"任意级标题截止"
  （修粘连 bug：声明节曾被吸成末条目续行）；③ 表3 长英文标识符列重叠修复（中文标签前置+全名入表注）；
  ④ 回归 134/104 tests OK；收尾清单新增引用可查证/AI 声明独立/阅读器目检三项；
  最终 res.pdf 146 页 + submission_body 22 页（clip 止于表7 y=240.2），四门禁全绿。

- [2026-08-26] **评审整改轮（代表点双轨 + v2 证据链入附录）**：① 4.2.2 改双轨语义——argmax 垂距规则
  降级为"独立参考膝点"（选中 eps_latency_25，0.314151），代表方案=phase 门禁指定（anchor_carbon，
  0.309322）；正文"代表膝点"13 处改名"代表方案"，frozen 标签同步 6 处，evidence JSON rule 改交叉核验
  语义并补 candidate_table_sha256（原为 null）；② q2_independent_check.py 重写为 v2 双轨校验
  （9 检查全绿；修 3 项既有失败：null 哈希 / scope_note 无"局部" / 跨工件 1e-7 浮点差→相对容差 5e-10）；
  ③ v2 solver 入证据链：executed_code_sources 白名单 +q2_lns_a1b_multiobjective.py
  +q2_lns_energy_system.py（=v2_baseline overlap 口径 q34_solver 的字节一致副本；去 sys.path 引导改
  同目录导入以过自包含门禁），附录自动重建为 B.1–B.9；④ 结论 `**` 字面残留清除。
  终版 res.pdf **235 页**（B.5/B.6=v2 实现，代码页增 88 页属预期），submission_body 22 页
  （p9"见附录B.5"为合法交叉引用），四门禁全绿。

- [2026-08-28] **Writer `search_papers` 坏参数续传崩溃已修**：真实任务
  `20260828-080924-3dd8912d8b76f6ff928175f0e2a9e7bb` 在 RepeatQues 阶段因原生
  `tool_call.arguments` 非法 JSON 于 Scholar 调用前抛错；`writer_agent.py` 现改为写历史前严格校验并
  canonicalize、同轮合法 pseudo-XML 仅恢复一次、不可恢复时返回配对 `invalid_arguments` 且不发空查询，
  同时恢复 Coder/Modeler 熔断上限 3/2。回归：定向 140 tests OK；全量 888 tests OK（skipped=2）；
  `ruff check .` 通过；Docker 挂载源码 76 tests + Ruff + `/docs` 健康检查通过。该任务仍为 failed，
  真实 provider resume 与论文全门禁尚未执行，禁止把手工 A 产物
  当正式候选；恢复脚本已保全至 gitignored `scratch/writer-b-recovery-20260828/`。

- [2026-08-29] **backend/ 根目录脚本位置口径（用户确认）**：目标为任务
  20260828-080924-3dd8912d… 的 28 个一次性脚本（inspect_*/patch_resmd_*/restore_*/
  set_preflight_pass.py/kw_top.py 等）+ check_task_status.sh，按用户口径**保留在 backend/
  根目录**（工作区代码树内、git 未跟踪、不入库）。后续 agent 在 git status 自检时将其
  视为已知预期文件，不得未经用户指令移动或删除。该任务现为 completed（取代 08-28 条目
  "仍为 failed"），res.md/docx/pdf/json 齐全、留有多份 .bak 人工备份；同批工作区另有
  4 个未提交门禁放宽源码改动（pdf_visual_checker.py 边距 0.6cm/正文 35 页/关键词任意页、
  paper_postprocessor.py claim_trace 缺失≤20 判 info、export_cli.py 接受
  CONDITIONAL_PASS、modeling_router.py resume traceback 日志），提交/回滚待用户指令。
  当日验收复核：隔离副本（tmp，已清理）用当前代码重跑 preflight 自然产出 PASS（仅
  editorial_quality/semantic_layout 两个 info 项）、pdf_visual PASS 149 页零未过项、
  submission_audit 默认+严格字体档均 PASS（SimSun/SimHei/Times New Roman 命中）；六门禁
  全绿 + TECHNICAL_PASS，manifest 哈希 5/5 MATCH，报告晚于正文定稿生成（链路新鲜）。res.pdf
  149 页 4.8MB（sha e2aa972b）。待人工：上传命名/匿名目检、源码干净重跑与引用在线核验未执行。
  当日收尾批 @ a1beddf：门禁放宽按 profile 收敛——0.6cm 边距/+20pt 右容差/35 页上限/
  关键词任意页/claim_trace≤20 不阻断全部限定 huashubei；cumcm2025/2026 恢复 2.5cm、
  20 页、首页关键词、claim_trace 严格，default 恢复 2.0cm；task-refresh 接受
  CONDITIONAL_PASS（硬 FAIL 仍拒）。回归：定向 121 tests OK、全量 888 tests OK
  (skipped=2)、ruff 全绿；隔离副本按 huashubei 复跑 preflight PASS + pdf_visual PASS
  149 页（min_margin_pt=17.01、max_body=35）。说明同步：PDF模板导出说明.md、STARTUP.md。
  补做验收两项：① 独立数学复算 35/35 PASS（scratch/acceptance-20260828-080924/，源码口径
  已对照 res.md 附录 B：Q1 重叠加权占用+基线负荷利用率+逐任务成本复算、Q2 五万行调度表
  求和+前沿无支配、Q3 SOC 同行递推残差 5.2e-5+终端≥初始+四降低率、Q4 基准场景全指标）；
  ② 文献在线核验：全文 0 行内引用 0 文献条目，按规程记录"无外部引用可核验"，数据来源为
  赛题附件 xlsx（已绑执行证据哈希）。两个低危观察待用户决策：5.3 节"SOC 恰好回到初始值
  水平"与数据不符（实际逐区域高于初始值，摘要/公式口径无误）；全篇无论文献区（历史 v2
  冻结稿有 8 条），补文献属内容改动需走受控链路。
