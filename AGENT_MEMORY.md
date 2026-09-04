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

- 论文 v23 已终版（09-04 18:09 收口链：85页正文30、五件全绿、缺字形含NUL类=0）；平台上传三件事
  （文件命名 / 匿名目检 / 诚信声明）待人工。tag v2026.08.24-paper-final 已在 origin(48a0e69)，
  如需 -f 移至 37391e8 另行指示。
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


- [09-03 LNS升级→不采纳] v2 LNS本机跑通（MILP 22s/次；threads致Not Set已修）但双重证伪：
  v2口径−0.4%被27%口径差吞没、share口径负优化−0.07%。产物留v2目录不进主链。
- [09-03 优化轮] Q1基线对照入正文；6.1.1真实OAT+表6弹性；表号1-8重排、空6.2删、6.3并7.2、
  关键词标准词。
- [09-03 评审二/三轮(90→91-92分)] 表3→非支配2.0、删旧审计文、压力模板×7、虚MILP×3、凸性收紧、
  Wilson误称×2、前沿用词与最优性措辞统一；18组网格真跑(最优100/5/0.1)，终测→54.7213/R²0.5084，
  协议cell入附录，frozen重绑；17条lead句并入图注。
- [09-03 评审四轮(定档92)] 图号语义修复（双编号/错号/旧章节号×6）；Q3目标去碳排放、Q1调度LP过度
  声明×3改贪心，调度器cell经验证补入附录闭合证据链。终态79页全绿，可冻结。
- [09-03/04 符号渲染专题] 表头BOM列错位、`$ \sum`开界空格吞中文、pandoc listings literate对λ/≤
  不生效→代码符号ASCII化(notebook与audit同步)、正文裸√∈tCO₂清理。终验缺字形0、12/12。
- [2026-09-04] LP fdd491 completed/TECHNICAL_PASS 但六维评审 NEEDS_REVISION（数值错/自检清单泄露/LaTeX 断行，详归档 09-03 节），待受控返修；PR #40 已合并 main（68cb89d），CI 905 项转绿。
- [2026-09-04] 门禁加固 PR #41：ALGORITHM_CLAIMS 扩 ε-约束/LNS/MILP/NSGA/退火（ε-约束需约束式证据，加权标量化不算）、结果/验收 CSV 字面量写死检测、preflight `$ ` 开界 lint、PDF 缺字形扫描、缓存键 SHA-256 规则；全量 921 项 OK。#43 补口：missing_glyphs 扫描集加 U+FFFF/U+FFFE（MuPDF 缺映射字形的实际输出字符）。
- [09-04 Q1调度器v3] 评审实锤v1未执行容量/时窗约束→EDF+分数重叠占用+纯电费+独立复算，538/538、三项违反全0。事故：替换边界串多处出现误删121行、恢复带回旧口径、二次scrub 7处修净——替换前校验边界唯一性、恢复后全量旧短语扫描。终态85页正文30全绿；16:52链曾与终版md脱钩且旧PDF含4个NUL缺字形，由新missing_glyphs门逮住、regen路线重发收口。详归档。
