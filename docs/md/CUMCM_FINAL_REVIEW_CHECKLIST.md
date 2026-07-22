# CUMCM 最终人工复核清单

## 使用时机

- `paper_preflight_report.json = PASS`，或 `CONDITIONAL_PASS` 且准备逐项人工复核并接受/修正条件项。
- `pdf_visual_check.json = PASS`
- `res.pdf` / `res.docx` 已生成后
- 正式提交前人工复核

自动预检只能检查格式门禁、基础证据链和低成本 PDF 风险，不宣称自动判断论文内容正确。
自动附录 B 现在会写入发现的完整可运行源码及每份源码的 SHA-256；
`final_acceptance_report.json -> complete_source_appendix` 会检查附录是否实际包含完整源码。
但自动报告仍不能替代人工运行源码、核对结果、阅读 PDF/DOCX 或确认最终提交规则。

当前 workflow 还会生成 `problem_contract.json`、`execution_validation.json`、
`execution_validation_report.json` 与 `frozen_results.json`。这些文件只能证明题面参数、
代码执行、可行性约束和数值来源可追溯；它们不替代人工复算、数值收敛检查或领域判断。

若正文与冻结结果发生可定位冲突，工作流会最多定向回修一次相应 Writer 章节并重新预检；
再次 `FAIL` 或无法定位的硬失败会停止 PDF 候选导出。此时先看
`paper_preflight_report.json -> checks` 和 checkpoint 的 `last_paper_preflight_failure`，
不要把旧 PDF 当作可提交产物。

## 摘要

- 是否说明研究对象。
- 是否说明建模方法。
- 是否说明主要结果。
- 是否给出结论。
- 是否避免空泛套话。
- 是否和正文结果一致。
- 关键数值是否与正文表格、图像、代码输出一致。

## 关键词

- 是否 3～8 个。
- 是否覆盖模型。
- 是否覆盖方法。
- 是否覆盖问题场景。
- 是否避免与标题完全重复但信息量不足。

## 问题重述与分析

- 是否逐问对应。
- 是否没有遗漏题目要求。
- 是否区分“题目条件”和“本文分析”。
- 是否没有引入题目未给出的关键条件。
- 是否说明每个问题的求解思路。

## 模型假设

- 假设是否必要、合理。
- 是否有明显与题意冲突的假设。
- 假设是否会影响主要结论。
- 是否避免把结论写成假设。
- 是否说明忽略因素的理由。

## 符号说明

- 主要变量是否出现。
- 单位是否清楚。
- 变量含义是否和公式一致。
- 同一符号是否没有重复表示不同含义。
- 参数、决策变量、中间变量是否能区分。
- 如果题目没有外部数据集，是否避免随机生成模拟样本、模拟数据集等数据驱动 EDA。
- 确定性参数题的预处理标题和文字是否使用“参数核验”“可行域核验”等表述，而不是样本数据意义上的“描述性统计”。

## 模型建立与求解

- 目标函数是否明确。
- 约束条件是否完整。
- 公式是否解释了变量和单位。
- 求解过程是否能和代码/表格对应。
- 是否说明求解方法或算法。
- 是否说明可行性条件。
- 是否说明最优解判断依据。
- 如果使用近似或数值算法，是否说明精度或停止条件。
- 若题目要求“控制时长”“分阶段升压/降压”或类似策略，是否对每个指定目标时刻给出可执行的
  控制数值、对应的压力核验值，以及过渡结束后切回/维持的稳态策略；不得只给正向仿真曲线。
- `execution_validation_report.json` 是否为 `PASS`；每个正式问题是否存在 `executed=true`、
  `feasible=true` 和能复核 SHA-256 的约束来源。
- [ ] 如存在 `quesN_acceptance_metrics.csv` / `quesN_constraint_check.csv`，是否逐行复核了数值、比较符、目标和“达标/状态”一致；不得把不满足约束的行标为通过，也不得用工具调用中的四舍五入数值替代表内精确来源。
- 每个约束来源和图表数据源是否由当前求解/定向回修回合实际新建或更新；不得把 checkpoint
  中未更新的旧结果文件重新登记为本次计算证据。
- `frozen_results.json` 中的指标是否与摘要、正文、表格和图题一致；不可行子问题是否没有被称为最优或已完成。
- 正文声明的遗传算法、Pareto、粒子群等方法是否确实在 notebook/可运行源码中有实现证据。

## 结果与敏感性分析

- 结果是否有数值支撑。
- `paper_preflight_report.json -> checks.result_consistency.passed` 是否为 `true`；
  若为 `false`，先按 `conflicts[].source` 对照结果 CSV 和 `conflicts[].sentence`
  修正文中关键数值。
- 图表是否被正文引用。
- 即使后处理已自动补齐缺失的“图N”文字引用，也要确认该引用与图题、前后论证和编号顺序一致。
- 敏感性分析是否真的回答题目。
- 敏感性分析是否说明参数变化范围。
- 敏感性分析结论是否和图表一致。
- 确定性参数题是否没有把 Monte Carlo、蒙特卡洛、随机模拟等探索性分析写成正式结论或支撑材料。
- 结论是否避免过度承诺。
- 是否区分模型内结论和现实建议。
- 正文是否避免混入突兀英文过渡词，如 `Overall`、`However`、`To conclude`。

## 图表

- 图表标题、编号、单位是否清楚。
- 图题是否是自然中文标题，不应直接显示 `.png`、下划线或原始文件名。
- 自动预检通过时，仍应人工确认表格的 `表n` 标题与正文叙述是否语义匹配。
- 宽表是否可读。
- 图片是否清晰。
- 图表是否出现在合适位置。
- 图表是否被正文引用。
- 仅列入支撑材料、未进入正文的图片是否确实只是辅助/中间结果；若是核心结果图，
  应插入正文而不是只放在附录A清单。
- 坐标轴、图例、色条是否可读。
- 表格小数位是否一致。
- 图片中文字是否不是乱码或方框。

## 参考文献

- 是否真实可查。
- 如正文引用外部背景、方法或数据来源，是否至少有基础来源；若全文无引用，是否确实没有需要支撑的外部事实。
- 正文引用编号是否对应。
- 自动预检会检查编号对应关系；人工仍需确认引用内容真实支撑对应句子。
- 若论文主题明确为燃油/液压等工程控制，是否没有混入区块链、国际商务等明显跨领域且不相关的参考文献。
- 参考文献编号是否连续。
- 引用内容是否支撑正文背景或方法。
- 是否避免伪造来源。
- 正文中是否没有孤立的 `: ... DOI ...`、英文文献残片或 definition-list 参考行。
- `paper_preflight_report.json -> reference_sources` 中 DOI/URL 基本格式、本地文件哈希和 `manual_review_required` 是否正常；逐条打开原始来源，确认其真实可获取并支撑对应表述。不得把本地格式/哈希通过表述为联网真实性验证。

## 附录和支撑材料

- 是否列出支撑材料。
- `support_materials_manifest.json` / `support_materials.zip` 如存在，是否仅含允许的源码、数据和必要结果，成员大小与 SHA-256 是否均与清单一致；它们仅在平台允许时另交，不能替代主论文文件。
- 支撑材料中是否包含完整可运行源码；同时检查 `final_acceptance_report.json` 的
  `complete_source_appendix=PASS`，并人工确认论文附录中源码可实际运行、与正文结果对应。
  不得将附录 A 文件清单或任务目录文件当作论文附录的替代。
- 若本次仅为阅读性而启用了 `paper_appendix_config.json -> mode=key`，附录 B 的关键伪代码/核心
  代码摘录只能用于人工理解，不能替代完整源码附录；此状态不得标记为 `TECHNICAL_PASS` 或用于正式提交。
- `paper_preflight_report.json -> checks.appendix_console_noise.passed` 是否为 `true`。
- 是否避免泄露本机路径、API key、真实身份信息。
- 论文正文/PDF 中是否没有承诺书、编号专用页、参赛队号、队员姓名、指导教师、学校名称等身份或封面字段。
- 论文正文、图表题、附录代码可见文本中是否没有 `用户`、`推断`、`估算`、`待验证`
  等提交痕迹或草稿口径词。
- 是否包含必要数据文件说明。
- 源码是否和正文结果对应。
- notebook 或脚本是否能说明主要图表来源。
- 对确定性题，源码附录中可见标签是否没有继续宣称 Monte Carlo/随机模拟为正式分析。
- PDF 文本中是否没有 `print(`、`printf`、`console.log`、`logger.debug` 等控制台输出痕迹。

## PDF 人工翻阅

- 摘要页。
- 摘要页是否独占第一页，第一页不应出现目录或正文“问题重述”等内容。
- 公式密集页。
- 宽表页。
- 图片页。
- 参考文献页。
- 附录源码页。
- 最后一页。
- 页边距是否看起来正常。
- 内容是否满足至少 2.5cm 页边距，尤其是宽表、长公式和附录源码。
- 页码是否正常。
- 是否存在明显空白页或截断页。
- 是否有代码、表格、图片超出页面。

## 最终提交前必须确认

- `paper_preflight_report.json = PASS`；若为 `CONDITIONAL_PASS`，必须逐项查看
  `severity=conditional` 的检查，正式提交前优先修正为 `PASS`，无法修正时需人工接受风险。
- `execution_validation_report.json = PASS`，`frozen_results.json` 的来源哈希仍有效；旧任务若缺少这些产物，不能按当前数学验收标准通过。
- `execution_quality_review.json` 的 `review_id` 与 checkpoint 中已批准编号一致；若状态曾为 `NEEDS_REVIEW`，逐项核对 `failed_subtasks/findings` 的修复结果或书面放行依据。机器筛查 `PASS` 只表示未发现明确失败标记/NaN/Inf，不能替代模型、量纲、守恒、推导和关键数值的逐题复核。
- 若使用过 Codex/人工受控候选，核对 `repair_candidate_manifest.json` 与 `repair_candidate_audit.jsonl`：候选必须绑定当前 `review_id`/`quesN`，`status=evidence_passed`，脚本和 evidence 哈希可复核；同时确认后续全量 execution validation、重新冻结和新的质量审批均已完成。单个候选 `evidence_passed` 不等于整题或论文验收通过。
- 质量复核返修后确认对应 `quesN_results.csv`、execution manifest、`frozen_results.json` 和论文章节均来自同一轮结果；不得用直接编辑 CSV/manifest/论文数字代替 Coder 重算和重新冻结。
- `paper_preflight_report.json` 中 `freeze_integrity`、`result_consistency`、
  `figure_result_consistency`、`infeasible_optimality`、`algorithm_evidence` 和
  `reference_relevance` 均为通过状态。
- `paper_preflight_report.json -> checks.result_consistency.passed=true`；该项只覆盖
  已结构化到结果 CSV 的关键事实，不替代人工复算模型和公式。
- 对变容、移动边界或多腔耦合模型，人工逐式核对 `d(ρV)/dt` 展开项和体积方向；
  结果数字与冻结表一致并不能证明论文没有漏写 `ρ dV/dt` 或写反 `dV/dt` 符号。
- `pdf_visual_check.json = PASS`
- `submission_audit_report.json` 已查看；`WARN` 可来自 Docker 字体 fallback 或
  `paper_preflight_report.json = CONDITIONAL_PASS`，必须确认原因；正式提交前如启用
  `--require-official-fonts`，结果应为 `PASS`。
- `pdf_visual_check.json` 中摘要首页、无目录、匿名电子稿身份字段、正文页数、文件大小和内容边距检查均通过。
- `paper_preflight_report.json -> checks.appendix_console_noise.passed=true`，附录没有
  批量控制台输出污染。
- `export_status.json -> pdf.font_resolution` 中正式字体没有被 fallback 为
  Liberation/Noto/AR PL 等预览字体；若曾 fallback，已挂载宿主机正式字体或在
  Windows 本机重导并复核。
- `res.pdf` 可打开。
- `res.docx` 可打开。
- `candidate_manifest.json` 的 `submission_file` 登记唯一主交付文件，并确认其存在、大小和 SHA-256 与清单一致。
- 正式上传只选择 `candidate_manifest.json` 所登记的当前主文件（默认 `res.pdf`）；不上传工作目录中的
  内部恢复候选 PDF（如 `res_recovery_candidate.pdf`）。
- `final_acceptance_report.json -> technical_status = TECHNICAL_PASS`；同时明确理解其
  `human_review.status = PENDING_HUMAN_REVIEW`，不能将技术通过表述为数学正确或可直接提交。
- 最终论文附录实际包含全部完整、可运行源程序；不要以附录 A 的文件清单、任务目录文件或
  `candidate_manifest.json` 代替论文附录内容。
- 团队已按 2026 规则复核 AI 生成内容的原创性、真实性和准确性；自动工具只可辅助，
  参赛队须对最终提交承担全部责任。
- 没有 API key / token / 本机路径 / 真实身份泄露。
- 如官方发布新模板，已按 `docs/md/CUMCM2026模板替换指南.md` 替换。
- 提交系统要求的文件格式、大小限制和命名要求已人工确认。
- 最终提交文件只包含竞赛允许提交的内容。

## P0-P2 补充复核项（2026-07）

### P0：产物与报告必须属于同一次导出

- [ ] `docx_export_status.json.success=true`，其 `source_sha256` 等于当前 `res.md`，`output_sha256` 等于当前 `res.docx`。
- [ ] `export_status.json` 的 PDF 源/输出哈希与当前文件一致；失败重导后目录中不存在冒充当前结果的旧 PDF。
- [ ] `candidate_manifest.json.schema_version=1.2`，`submission_file`、`artifact_set_id` 与主产物哈希已生成且一致。
- [ ] 如生成支撑材料，`support_materials_manifest.json` / ZIP 已通过成员、大小和 SHA-256 审核，且明确不作为主论文上传文件。
- [ ] `task_status.json` 为权威状态；`finalizing` / `failed` 不因旧 `res.md` 或 `res.docx` 存在而显示为 completed。

### P1：结构与逐页视觉

- [ ] `pdf_visual_check.json.scan_scope=all_pages` 且 `pages_checked=page_count`。
- [ ] 正文没有 Markdown 表格源码泄漏、重复参考文献章节、孤立文献编号或内部审查图片。
- [ ] 人工逐页确认图题没有跨页误配、最后一页没有仅剩极少量代码、附录代码可读。

### P2：内容语义与复现

- [ ] 每张正文图都有“图N”正文引用，并与图题和分析结论对应。
- [ ] 连续型模型的小数解写为“连续生产当量”；若业务要求整件，单独求解整数规划，不直接四舍五入。
- [ ] 影子价格写明有效区间/最优基条件，不能把局部边际价值无限外推。
- [ ] 坐标轴顶点由哪条约束决定的解释，与实际等式和可行性计算一致。
- [ ] 附录代码包含完整导入、参数、求解、校验断言、结果文件和作图调用；正式支撑材料另保留依赖锁定与运行说明。
- [ ] `reproducibility_manifest.json` 已生成；其运行环境和入口仅记录本轮证据，`replay_status=not_independently_reexecuted` 时不得声称已独立复跑。
- [ ] 非 `not_applicable` 的诊断 profile 有源码实际产出的对应收敛、残差、可行性、拟合或仿真复现实证；不能只在论文中宣称“已验证”。
- [ ] 已人工复核 `similarity_ai_risk` 提示；它是本地草稿风险筛查，不是正式查重、AI 检测或抄袭结论。
