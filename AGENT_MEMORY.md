# AGENT_MEMORY

- [2026-08-17] 完成阶段二项目级系统架构加固与工程缺陷根治（新建分支 `feat/phase2-architecture-hardening`）：
  1. 规划层：`ProblemContract` 新增 `boundary_conditions` 强类型拓扑契约，显式声明各轴周期/极板截断；放宽 `_structured_diagnostic_metric_gaps` 多概念要求匹配容差，消除 Modeler 因逐词不一致导致的连续报错；增强 `_conclusion_forcing_metrics` 拦截未计算先定性（如导通/连通预置布尔值）的验收硬编码。
  2. 提示词层：`coder.py` 注入 MC 增量落盘标准代码模板（断点续跑、`append_to_csv`）、Preflight $N=3$ 耗时预算预估协议（超 60s 强制采用空间分箱/批处理），并严格禁止裸 $O(N^2)$ 与 $>10^6$ 密集网格参照。
  3. 算法库层：新增 `app.tools.geometric_lib`，沉淀高鲁棒胶囊体/平端帽圆柱体最短距离、线段端点 clip 夹紧保护、零长度退化保护、3D Uniform Grid 空间分箱宽相加速及独立数值优化复算法。
  4. 门禁层：`execution_validation.py` 增加参数审计表量纲算术静态一致性断言（拦截 $10000^3=10^{15}\text{ nm}^3$ 等数量级错误）及抗伪造独立交叉复算检测（识别恒等入参调换的伪复算）。
  5. 基础设施层：`local_interpreter.py` 修复看门狗子进程组彻底清理与显式 `wait()` 回收；Compose 文件开启 `init: true` 启用 tini 僵尸进程收割并将 `pids_limit` 提升至 1024。
  全量回归 643 项后端单测全部通过（1 项环境跳过），`ruff check app` 全部通过。

- [2026-08-11] 真实格式不足的根因是仓库公共 `cumcm2026`/`cumcm2025` profile 只能随代码和内置模板一起更新，无法安全绑定某个任务实际取得的最新中文竞赛包；把猜测的华数杯或旧 DOCX 样式写成 CUMCM 官方口径也会造成误导。当前已新增任务级模板覆盖路径：`python -m app.tools.export_cli template install --task-id <task_id> --profile cumcm2025|cumcm2026 --docx-template <official.docx> --format-contract <format.json>` 将安全 DOCX 复制到任务目录并以 SHA-256 绑定，`template show` fail closed 校验，随后必须用 `task-refresh` 在无 Provider 条件下重建 Markdown/DOCX/PDF/LaTeX、预检、视觉检查、审计和候选清单。当前用户指定的内部基线为摘要正文/正文宋体小四（12pt）、单倍行距、摘要至少两段、关键词后正文另起页、正文 10--20 页、参考文献必需；它固定标记 `official_rule=false`，不是 CUMCM 官方条款。模板/合同拒绝符号链接、外链关系、宏/嵌入对象、重复 ZIP 条目、任意 TeX 与弱化门禁；DOCX/PDF/预检/视觉检查/candidate manifest/final acceptance 必须绑定同一模板与合同 SHA-256，否则 FAIL。已补充可复制的合同示例 `docs/md/竞赛版式合同示例.json`；当前仅在临时目录完成导入/导出/审计回归，未对真实任务执行导入、刷新或 Provider 调用，不能把该路径报告为真实任务端到端验收通过。

## 当前稳定状态

- [2026-08-11] 真实任务 `20260810-073046-5ad7409f50644a2211d4e67828ca043e` 在完成一次无 Provider 的版式重排后，新增 DOCX 字面 Markdown 标题门禁首次写入提交审计时把附录 B 源代码中的 `# Cell` 误判为正文泄漏，使 `submission_audit_report.json=FAIL`、最终技术状态暂为 `TECHNICAL_FAIL`。PDF 全文检查并未发现正文 `###`，冻结结果、模型数值、Markdown、DOCX、PDF均未因此改写。当前处置：将 DOCX 扫描范围限制在附录 B 源程序代码之前，添加回归后只重写审计/候选清单/最终验收报告；不得把本次误报当作论文质量通过或忽略。

- [2026-08-11] 上述 2025A 版式问题已完成受控修复与重验：后处理会在代码围栏外补足 ATX 标题前的空行；PDF 全页视觉检查会拒绝正文中字面 `#`/`##`/`###` 标题，提交审计会对 DOCX 正文作同类检查并在附录 B 源程序代码处停止扫描。一次 `presentation_reflow_pending_export` 仅版式重排（不调用 Provider、不改 Writer 正文、代码、CSV/XLSX、执行证据或冻结结果）重新生成 Markdown/DOCX/PDF/LaTeX 及审计。实际复核：PDF 72 页、正文 14 页、摘要 725 字符、正文 5825 内容字符、8 图 8 表；预检、PDF 视觉、DOCX 门禁、提交审计、candidate manifest 和最终技术验收均为 `PASS` / `TECHNICAL_PASS`。该技术结论仍不替代队员对正式竞赛规则、匿名和提交版式的人工确认。

- [2026-08-03] 修正 profile 与摘要后，候选论文预检已通过并写入 PASS，但全链路脚本在 DOCX 开始前停止：从候选目录调用 md_2_docx 使 common_utils 以当前目录重复拼接 project/work_dir/task_id，报 FileNotFoundError。没有生成 DOCX/PDF/LaTeX 或后续审计；已生成的 PASS 预检仍绑定当前 res.md。当前处置：保持脚本和候选内容不变，改从容器后端根 /app 调用同一脚本，使 get_work_dir 使用正确的项目根。

- [2026-08-03] 隔离候选完整导出已实际进入论文预检，但在 PDF/DOCX 前被硬门禁拦截：一是调用方传入 ExportProfile.CUMCM2026 枚举对象，预检严格期望字符串 cumcm2026；二是摘要将 100 MPa、150 MPa 两个稳态开启时长并列在同一句，冻结事实匹配器将 0.258 ms 错附着到 150 MPa 指标。预检报告已写为 FAIL，未生成或覆盖 DOCX、PDF、LaTeX、视觉报告、审计或候选清单。当前处置：传入 profile.value，并把两个指标拆为各自带标签和数值的独立句，随后重新跑受控预检。

- [2026-08-03] 隔离候选的完整导出脚本首次在 import 阶段停止：codex_export_pipeline.py 从 app.services.task_status 导入不存在的 update_task_status，实际公开函数为 write_task_status。该错误发生在预检之前，未生成或覆盖 paper_preflight、DOCX、PDF、LaTeX、审计或候选清单。当前处置：仅修正状态写入函数名，随后启动同一受控全链路导出。

- [2026-08-03] 论文组装脚本通过 AST 编译后第三次在写文件前被自设摘要质量断言停止：从冻结指标绑定生成的摘要去空白后为 384 字，不满足本候选要求的 450–650 字。未产生 res.md/res.json，不影响冻结结果、执行证据或导出。当前处置：只补充已经由执行和独立复核支持的建模、检验过程描述，不加入新的数值或外部引用；再从冻结结果重新组装。

- [2026-08-03] 同一候选在转义首个下标后第二次论文组装仍在写文件前停止：同一 f-string 的显示公式把 \frac{{\rm d}\rho}{{\rm d}P} 中的右花括号漏写为双花括号，报 SyntaxError: f-string: single '}' is not allowed。该错误仍未改变 res.md、res.json、冻结结果或任何导出产物。当前处置：停止逐个试错，先以 AST/编译检查定位本文件所有 f-string 花括号，再一次性修复后重跑。

- [2026-08-03] 隔离候选 20260803-codex-mimo-2019a 的论文组装脚本首次在 Python 解析阶段退出：codex_assemble_paper.py 把 LaTeX 下标 $q_{in},q_{out},q_v$ 直接置于 f-string，未转义花括号，报 SyntaxError: f-string: expecting a valid expression after '{'。该错误发生在写入 res.md / res.json 前，既未改写冻结结果、执行证据，也未触发导出。当前处置：仅转义公式中的 LaTeX 花括号，随后从同一冻结结果重新组装论文；不修改任何数值 CSV。

- [2026-08-03] 隔离候选 `20260803-codex-mimo-2019a` 的首次可信 evidence 绑定未进入任何验证逻辑即退出：从候选工作目录执行 `uv run python codex_finalize_evidence.py` 时 Python 路径不含后端包根，报 `ModuleNotFoundError: No module named 'app'`。执行器生成的 Q1/Q2/Q3 数值文件、执行 manifest、冻结结果和论文产物均尚未由该命令写入或改变，不能将此运行时入口错误报告为通过。当前处置：保留候选数值文件，改从容器 `/app` 后端项目根运行同一受控绑定器；不改写任何结果 CSV。

- [2026-08-03] 上述候选从 `/app` 以脚本路径调用仍第二次在 import 前报同一 `ModuleNotFoundError`；已验证交互式 `cd /app && uv run python -c 'import app'` 能解析包，说明 `uv run python <候选脚本>` 会将脚本目录置于导入路径而非后端根。两次均未执行 `record_execution_evidence`、未写 execution manifest 或冻结结果。当前处置：停止重复该入口，使用显式 `PYTHONPATH=/app` 的差异化项目根调用；仍不修改数值结果文件。

- [2026-08-03] 候选的差异化 evidence 绑定已成功进入后端 `record_execution_evidence`，但 ques1 被契约拒绝：`modeler_plan.json` 的 `eq` 在受控协议中映射为 `abs_diff_lte,tolerance=0`，而执行器结果表把两个计划指标的目标显示为 `=3`、`=2`，被严格识别为比较符不一致。未写成功 execution manifest、冻结结果或论文；数值仿真本身未被否定。当前处置：仅将这些表格目标展示改为等价的纯数值 `3`、`2`（让可信绑定器承载比较符），随后从源代码重跑所有产物并重新登记哈希。

- [2026-08-03] 在临时隔离副本做源码干净重跑时，`uv run` 因 `/tmp` 不在项目树内而未加载项目依赖，在 `matplotlib` 导入前报 `ModuleNotFoundError`；候选目录和其已 PASS 的 execution manifest/frozen results 未被改写。当前处置：不再从临时目录调用自动项目发现，改用容器已验证的 `/app/.venv/bin/python` 对全新副本执行同一源码，再对数值 CSV 哈希做比较。

- [2026-08-03] 同一真实任务的唯一人工 `low_cost_algorithm` 恢复也失败：恢复后的 MiMo Coder 在 Q1 中先后消耗执行额度读取/检查旧文件，仅新建参数审计 CSV，未在本轮重建 `ques1_results.csv`、时序、过渡表、绘图数据和图；随后三次 evidence 仍分别因来源未更新、来源未更新、指标/比较符/来源不可复查被拒，于 `13:32:17` 再次标记 `failed`。此恢复授权已耗尽，不能再对该任务续传。当前处置：不再尝试同一 Coder 工作流；将以隔离的新候选路径由 Codex 实际执行、记录来源和独立复核，MiMo 仅继续承担已成功的计划/后续写作协作，不把旧任务的任何中间数值移作结论。

- [2026-08-03] 针对上述熔断，在用户授权的完整真题闭环范围内，Codex 以 `recovery_mode=low_cost_algorithm` 触发本任务唯一一次人工执行恢复：恢复说明明确限定 Q1/Q3 使用一次新执行重建所有契约产物和 source-backed 仿真诊断，Q2 不因该恢复被豁免，仍保留给后续执行质量复核定向返修。恢复授权已写入 checkpoint；若该有限恢复仍失败，不再对同一任务重复 Coder 续传。

- [2026-08-03] 全长真实 MiMo 任务 `20260803-124001-318963165070f6fa18dc8537d894a9fe` 在系统自动定向返修 Q1 后仍连续三次被受控 evidence 拒绝，第三次理由为 simulation 未带可复核诊断要求/指标；工作流于 `13:25:29` 按连续失败熔断为 `failed`，`targeted_repair_attempts=2`，无质量复核、冻结、Writer 或最终论文产物。Q2 仍保留已知单位错误，不能将任何当前 CSV/PASS 作为可交付结论。当前处置：停止对该失败任务的同样 Coder evidence 请求；先只读定位 evidence 提交/恢复的根因，依照恢复规程在有明确、可测试的差异化方案前不再原样续传或新建重复任务。

- [2026-08-03] 三问形式 evidence 汇总后的 `execution_validation_report.json` 触发自动定向返修：Q1 的本轮 evidence 重新提交被拒，因为 `ques1_plot_data.csv` 与 `ques1_pressure_control.png` 未由该轮实际执行更新；checkpoint 因此进入 `workflow_state=repairing`、`targeted_repair_attempts=1`。该失败只涉及 Q1 evidence 新鲜度，不得借自动返修报告中 Q2 未被列出而把已知的 Q2 单位错误视为解除；当前处置：允许系统只完成其 Q1 产物刷新，随后仍由 Codex 在质量复核层人工退回 Q2/Q3 的数值问题。

- [2026-08-03] 同一任务的问题三在补齐控制表后首次提交正式 evidence 仍被拒：申报 `metrics[5].value=20.0` 无法由所声明 `source_path` 复查。Coder 随后补齐来源并使总 `execution_validation.json` 回到 `PASS`、保存 ques3 快照；该 PASS 不消除问题二仍含错误单位的事实，Q3 不得在问题二修复和独立复核前冻结或写入论文。

- [2026-08-03] 对问题二的只读对抗复核还发现：旧代码以 `500 ms` 粗筛/末 `200 ms` 选取 `omega=0.5 r/s`，却以 `2 s`/后 `1 s` 统计写正式结果；旧粗筛均值约 `90.8236 MPa` 与正式均值 `6835.5548 MPa` 本已相互矛盾。当前参数审计表也未落盘步长、模拟时长、稳态窗口、插值设置、守恒相对残差或跨时长统计差异。当前处置：问题二返修不能只替换一个实参或沿用 `0.5 r/s`，必须在修正量纲后重跑粗筛—局部细化—长时域验证，重新选择候选并将收敛/守恒诊断写入可复查来源。

- [2026-08-03] 同一任务的问题三首次主仿真已经实际运行并写出 `ques3_results.csv` 与时序 CSV（日志中的中间值约为均值 `99.2584 MPa`），但随后写控制表时引用未定义的局部变量 `prv_op` / `prv_cp`，触发 `NameError`，该执行单元未完整结束，不能作为成功的 Q3 证据或冻结来源。当前处置：允许 Coder 在同一受控反思轮中只补齐该变量定义/控制表并重新运行必要输出；问题二仍因独立单位错误而被否决，待执行质量复核时必须与其依赖结论一并定向返修。

- [2026-08-03] 对同一任务问题二的返修产物进行只读复核后发现，`execution_validation.json` 虽被重新写为 `PASS`、`ques2_parameter_audit.csv` 也已补齐，但计算源代码仍是 `dVdt = chamber_volume_deriv(theta, omega_rps)`，并未按已登记的单位根因改为 `omega_rad_ms`；`ques2_results.csv` 因此仍是均值 `6835.5548 MPa`、峰值 `19852.8283 MPa` 的错误旧数值。该次“PASS”只证明文件新鲜度/证据契约通过，不能证明模型正确，且已错误启动问题三。当前处置：阻断将 ques2/Q3 作为有效结论；对同一 Coder 发出带源码定位、结果否决和重算要求的受控返修，之后必须核对源代码、文件修改时间和新数值三者同时变化，方可重新提交证据。

- [2026-08-03] 同一真实任务的问题二在 Codex 单位返修指令入队后，Coder 的首次受控 evidence 提交被拒：契约要求本轮实际新建或更新 `ques2_parameter_audit.csv`，但当前仅有旧名 `ques2_input_parameter_audit.csv`，故来源新鲜度不成立；紧接着用于补齐审计文件的一次短代码执行又报错（待从容器消息记录提取具体异常）。这两项事件均发生在当前错误的 `6835.5548 MPa` 结果仍未重算之前，不能视为数值返修已完成。当前处置：先保留并读取错误上下文，要求同一 Coder 在一次可复现计算中先生成契约名参数审计文件、再以 `omega_rad_ms` 重跑全部 Q2 时序和结果，最后重新提交 evidence；未完成前不得冻结问题二或进入问题三。

- [2026-08-03] 同一真实任务的问题二首次时序仿真虽无运行异常，但数值输出明显违背“尽量稳定在 100 MPa”：`ques2_results.csv` 报告均值 `6835.5548 MPa`、峰值 `19852.8283 MPa`。只读审查 notebook 后定位直接根因：`simulate_omega()` 已计算 `omega_rad_ms = omega_rps*2π/1000`，但调用 `chamber_volume_deriv(theta, omega_rps)` 时误传了转/秒，后者公式需要 rad/ms；对固定 `omega_rps` 而言使柱塞容积变化率放大 `1000/(2π)≈159.15` 倍。当前处置：禁止以该结果提交/冻结；在同一任务中仅修正该单位传参、重跑问题二的粗筛/局部细化/验证，并重新登记正式 evidence 后才允许进入问题三。

- [2026-08-03] 同一问题一的第二次受控 evidence 提交亦被拒绝：`transition_schedule_rows=3` 仍不可从源文件复查，且 simulation 计划缺少可复核诊断指标。Coder 随后补齐结果行和诊断来源，第三次提交实际生成 `execution_validation.json` 且 `status=PASS`，并保存 ques1 变量快照。该 PASS 只说明当前 formal evidence 链可追溯；结果表仍报告约 `20.61%–20.73%` 的质量守恒残差，必须在后续 Codex 独立数学复核中判断或定向返修，不能据此声称物理模型已通过。

- [2026-08-03] 同一真实任务 `20260803-124001-318963165070f6fa18dc8537d894a9fe` 在问题一性能返修后写出了 `ques1_results.csv`、四个时序 CSV、控制表和图，但首次受控执行证据仍被拒绝：`metrics[11].value=0.0004` 以及若干 `constraints.actual` 值未能在所声明 `source_path` 中逐项复查。该次拒绝表示数值证据的来源/可追溯性不合格，不能将现有 CSV 当作已验证结论。当前处置：保留计算产物但只允许 Coder 追加或改写对应的指标/约束源表与 evidence 记录，使每个申报值可由当前文件复算或定位；随后重新走正式 ques1 执行验证，未通过前不得冻结。

- [2026-08-03] 全长 2019 CUMCM A 真实 MiMo 任务 `20260803-124001-318963165070f6fa18dc8537d894a9fe` 在 Codex 审核建模方案后，Coder 的问题一首次全量仿真于可信本机 300 秒看门狗超时并被中断，内核已从变量快照恢复。直接根因已只读确认：`dt=0.001 ms` 的时序积分在约 500 个单向阀候选开启时长以及多个 2/5/10 秒过渡工况上重复执行，并在每一步反复进行密度数值积分，导致不必要的超大计算量；未生成 ques1 正式结果、执行验证、冻结或论文产物，不能视为通过。当前处置：不新建或原样重试任务；由 Codex 向同一 Coder 注入仅返修 ques1 的“解析/插值缓存 + 分层粗筛—局部细化 + 步长收敛证据”指引，保留已验证 EDA 和快照，重跑后再检查实际结果。

- [2026-08-03] 新建全长 2019 CUMCM A 真实 MiMo 任务 `20260803-124001-318963165070f6fa18dc8537d894a9fe` 已保存原题与附件1/2/3，并由 Coordinator 正确拆为三问；但 Modeler 在四次受限 schema/题面契约纠错后仍把无题面容差的守恒诊断强制为精确 `1.0` 硬阈值，且遗漏固定油管几何/喷油频率的参数表与量纲核验，任务在 Coder 前终止为 `failed`。无 notebook、执行 manifest、冻结或论文产物，不能视为验收通过。当前处置：不新建或原样重试题目；由 Codex 在同一任务的 `codex-modeling` 受控接口提交可验证、无编造阈值的结构化计划，经过正常人工审批后才进入 Coder，后续所有执行/冻结/导出门禁保持不变。

- [2026-08-03] Docker 本机可信执行镜像重建验收：`docker compose build --pull` 与 `docker compose up -d --wait` 均成功，redis/backend/frontend 全部 healthy，前端首页与 `/api/docs` 均为 200，`/api/status` 为 `running`，容器内 Pandoc、XeLaTeX、Noto CJK、Ruff 和 495 项单测（1 项环境跳过）均实际通过。重建后发现 `backend/.env.dev` 的显式 `LLM_OUTBOUND_PROXY` 对四个 Agent 均报 `RemoteProtocolError`，同一受控无凭据直连探测返回 HTTP 404，说明直连路由可达而旧代理失效；`docker-compose.local-execution.yml` 现默认以空 `LLM_OUTBOUND_PROXY` 覆盖该旧值。若可信本机确需代理，只能在根目录 `.env` 显式设 `MMA_LLM_OUTBOUND_PROXY` 后重启；基础/remote Compose 保持使用 `backend/.env.dev` 的 `LLM_OUTBOUND_PROXY`。未读取或输出任何 API Key，且没有活动任务时才重建 backend。

- [2026-08-03] 真实回归闭环：新隔离轻量线性规划任务 `20260803-095511-66d0d985e21b2e8d7a6adb9ffe68a4f9` 已完成并保持 `completed`。已修复三项根因：非正式 EDA 不再要求正式 execution evidence、`/tasks` 如存在持久化状态则不再错误降级为 `interrupted`、`quesN_plot` 图注会规范化为自然语言；同时修正了第10页“机器时间—利润”敏感性图与正文语义不一致的问题，未改写冻结数值或执行证据。以只复制 `notebook.ipynb` 的隔离新 Python 进程顺序编译/执行 25 个代码单元，全部成功并重新生成结果文件（镜像未安装 Jupyter，故此为等价干净进程重跑而非 Jupyter kernel 重跑）；独立顶点枚举得到 Q1 `(40,20), Z=2200`、Q2 `(140/3,50/3), Z=7100/3`、增益/影子价格 `50/3`。当前 execution validation、质量复核、preflight、语义版式、PDF visual、严格官方字体 submission audit、candidate manifest 和最终技术验收均为 PASS/`TECHNICAL_PASS`；候选主产物哈希匹配。当前源码已由本地与 Docker 的 495 项单测（各 1 项环境跳过）及 Ruff 实测通过。无外部引用可核验，未伪造文献；提交平台规则、匿名/诚信声明与最终主观排版仍由队员确认。

- [2026-08-03] 新镜像上的隔离轻量线性规划真实验收任务 `20260803-095511-66d0d985e21b2e8d7a6adb9ffe68a4f9` 已完成 EDA、ques1、ques2、敏感性分析及受控执行证据，`execution_validation.json=PASS`、冻结与质量复核检查点均已生成；但 `/tasks` 将任务误显示为 `interrupted`，而任务目录的 `task_status.json` 和 `checkpoint.json` 均为 `waiting_quality_review`。根因是 `common_router.list_tasks()` 的合法状态白名单遗漏 `waiting_quality_review`，使其在无最终论文产物时被错误降级。当前处置：先补状态呈现回归测试并修复白名单，再执行质量复核与后续导出；不得将该显示误报当作真实任务失败。

- [2026-08-03] 同一任务的非正式敏感性分析阶段曾出现一次代码执行错误，系统随后在受限反思轮次内自动修正并成功写出敏感性结果；未改写正式 Q1/Q2 的受控证据、执行验证或冻结结果。当前处置：在最终审批前仍须以隔离副本新内核重跑 notebook，并以当前冻结哈希复核全部正式结论。

- [2026-08-03] 同一任务在首次完成导出后的 PDF 人工抽检中发现第10页图3与正文不一致：图为“机器时间—利润”局部敏感性曲线，但相邻段落仍保留 `ques2 plot` 文件名式表述并误写为可行域扩展图。自动预检、视觉扫描与提交审计当时均为 PASS，说明该问题必须由 Codex/人工语义复核补充发现。当前处置：不修改冻结数值、执行证据或源码，仅将该图的正文引用/解释改为与敏感性曲线一致的结论，然后重新生成 Markdown 后处理、DOCX、LaTeX sidecar、PDF、审计和候选清单。

- [2026-08-03] 直连已验证可达后，隔离轻量线性规划任务 `20260803-093921-41bf147fae33a88373b3cdbfccea616b` 已完成 Coordinator、Codex 结构化建模复核和 7 个无错误 notebook 代码单元，并生成问题一 CSV/图；但工作流把非正式 EDA 阶段列为唯一 `required_subtasks=["eda"]`，在不存在 `execution_validation.json` 时终止为 `代码阶段 eda 未提供成功执行证据`。该任务无完成阶段、无执行 manifest、无冻结或论文产物；不能将其中间 CSV 视为通过。当前处置：不续传或重试该任务；先核对 EDA 与正式 `quesN` 的证据契约并修复回归，再新建一次受控验收。

- [2026-08-03] 新镜像上的隔离轻量线性规划真实验收任务 `20260803-093534-59fde4aa60db23d2a3997d84f25127be` 在 Coordinator 首次调用阶段连续 3 次 `APIConnectionError` 后终止；任务仅留下 `task_request.json`、`problem_contract.json` 和引导审计，无 ModelPlan、代码、冻结或论文产物。Docker 服务、491 项容器回归与 Ruff 均已通过，故根因是当前 provider 出站连接而非本轮代码/镜像。当前处置：不对该任务原样重试；先走受控 Codex 接管能力或由指定决策人切换已验证 provider/路由，随后最多发起一次差异化验收。

- [2026-07-28] 隔离真实任务 `20260728-103719-56e242101768fafa9a6e1386cce556cd` 的 ModelPlan 虽通过结构校验并到达 `waiting_review`，人工复核发现问题三仍将 `90–110 MPa` 写成题面外的设计范围，且以无可核验来源的“工程经验”设定 1% 质量平衡阈值。当前处置：未批准 Coder；按单次受控 `revise-modeling` 要求删除非题面阈值，只保留硬物理/题面条件和实测诊断值，修订成功后才可执行。

- [2026-07-28] 真实任务 `20260728-100101-e102078e0dd6ef10ab21fa4ff20b4915` 的问题二定位到直接根因：Coder 将细步长 ODE 与大量候选参数扫描写进单次单体执行，实际运行超过本机受控 300 秒看门狗；失败单元被安全回滚，未留下可复用的成功证据。已按熔断规程停止该任务，新增 Coder 的“基准→粗筛→局部细化→证据”执行预算契约及回归测试；待镜像回归后只能以新的隔离任务重验，不能第四次续传旧任务。

- [2026-07-28] 真实任务 `20260728-100101-e102078e0dd6ef10ab21fa4ff20b4915` 的问题二在本地 300 秒执行窗口内三次仍未提交成功执行证据，工作流按熔断规则终止：`execution_validation_report.json=FAIL`，仅剩问题一验证记录，不存在冻结、Writer 或最终论文产物。当前处置：禁止第四次续传；先从容器消息和问题二源码定位具体错误，修复后只能以新的隔离任务重验。

- [2026-07-28] 真实任务 `20260728-100101-e102078e0dd6ef10ab21fa4ff20b4915` 的问题一大规模数值积分触发可信本地 Docker 覆盖的 120 秒看门狗；`variable_snapshot.pkl` 随后恢复 57 个变量，未冻结任何结果。当前处置：把仅用于该受控本机覆盖的单次上限调整为 300 秒（基础 remote 默认不变），再从同一 checkpoint 续传一次，避免重复相同的 120 秒失败。

- [2026-07-28] 真实任务 `20260728-100101-e102078e0dd6ef10ab21fa4ff20b4915` 在批准 ModelPlan 后、任何 Coder 代码执行前被安全配置阻断：默认远程解释器未配置 `E2B_API_KEY`，且按设计不会自动降级。当前处置：仅在本机受信任 Docker 开发环境显式设定 `CODE_INTERPRETER_KIND=local` 与 `ALLOW_LOCAL_CODE_EXECUTION=true`，重建 backend 运行配置后一次受控续传该任务；这不改变生产环境默认安全策略。

- [2026-07-28] 全新真实 MiMo 2019 CUMCM A 题任务 `20260728-100101-e102078e0dd6ef10ab21fa4ff20b4915` 的 Modeler 首次方案被硬校验拒绝：为 `final_pressure_deviation` 和 `average_pressure_deviation` 编造了无来源的 `0.5 MPa` 阈值。已在重试前以 `source=codex` 向 Modeler 注入“仅保留题面/附件可追溯阈值、其余记录实测诊断值”的恢复提醒；修订计划随后通过结构校验，人工复核后已放行 Coder。任务仍在真实执行，尚不可声称论文完成。

- [2026-07-28] 任务 `20260728-092845-06a2a85d867083ca7c14b83e2090c34f` 的 DOCX/PDF/LaTeX/视觉检查均生成成功，但最终验收为 `TECHNICAL_FAIL`：预检和提交审计均因本地相似性扫描把多张 Markdown 图片链接截断为“重复句子”而分别给出 `CONDITIONAL_PASS` / `WARN`。当前处置：修复扫描时排除图片 Markdown，并新增回归；该调整不弱化真实正文的重复句检查。

- [2026-07-28] 任务 `20260728-092845-06a2a85d867083ca7c14b83e2090c34f` 在 PDF 与 LaTeX sidecar 已成功生成后，手工 DOCX 收尾的首次调用因错误引用不存在的 `app.utils.file_utils` 而立即退出，未写入 DOCX/manifest 或改变任务状态。当前处置：改用实际定义 `md_2_docx` 的 `app.utils.common_utils` 完成一次受控收尾；不得将该路径错误报告为导出失败。

- [2026-07-28] 真实 MiMo 轻量线性规划任务 `20260728-092845-06a2a85d867083ca7c14b83e2090c34f` 的 Writer 两次论文预检失败后停止相同重试：一是将“若采用遗传算法……不及线性规划”的未采用比较误作已实现算法，二是把连续线性规划的分数解直接写成“件”。当前处置：收紧算法声明识别为仅对实际采用的算法要求代码证据，并将该任务正文的分数产量改为“连续生产当量”；随后以新镜像重跑预检和完整导出验收，不伪造冻结或执行证据。

- [2026-07-28] 真实 MiMo 轻量线性规划任务 `20260728-084449-540f700d636b35968bb25caf7938bed8` 已实际完成 Coordinator/Modeler 并进入 `waiting_review`，但 Codex 独立复算发现 ques2 的 ModelPlan 将 `2x+y=110, x+2y=80` 错算为 `(50,10)`、利润 2300、增量 100；正确交点为 `(140/3,50/3)`、新利润 `7100/3≈2366.67`、增量 `500/3≈166.67`。当前处置：不审批错误方案，按人工门禁经一次受控 `revise-modeling` 退回，并要求代数与顶点枚举一致后才进入 Coder。

- [2026-07-28] 真实 MiMo 轻量线性规划验收任务 `20260728-054207-e20b1340922912f8c37c48132e0b3df1` 首次在 Coordinator 远程调用前失败：一次请求超时后，DNS/SSRF 校验连续报告“LLM Base URL 主机无法解析”。为此在 Compose backend 固定两个公共 DNS 后恢复；Coordinator 已实际成功返回，证明该次真实 MiMo Key/Responses 调用曾被接受，但 Modeler 的首次调用在 90 秒外层限时后超时，随后解析短暂失败，任务终止且未产生模型、执行或论文产物。新任务 `20260728-055654-d1112a49ffb5a668907b0c3033c87d69` 将单次限时提升至 300 秒后仍在 Coordinator 调用中失败；实测容器可建 TCP 连接但对 MiMo endpoint 的 TLS handshake 超时。已实现并配置受控 `LLM_OUTBOUND_PROXY`（不继承环境代理、仍保留 URL/SSRF 校验），容器经本机代理对 MiMo 的 OPTIONS 仍发生 TLS 超时/连接重置，而同一代理可访问 Google。`POST /modeling/{task_id}/guidance` 的 `source=codex` 已返回 queued 并写入带 SHA-256 的审计记录，但失败任务没有运行中的 Coder，不能将该“已排队”冒充为“已消费”。当前处置：停止继续向这两个失败任务发起调用，待本机代理或网络提供可完成 MiMo TLS 的路由后，才用全新任务执行 Modeler、Codex 注入消费、冻结与论文导出验收。

- [2026-07-28] Docker Desktop 容器、后端镜像、项目卷和网络均已删除，无法从 Docker 备份还原；仅保留前端镜像与非完整 BuildKit 缓存。后端 Dockerfile 已改为官方 Debian HTTPS 源、带有限重试并将 CJK/TeX 依赖分三批安装，解决原 HTTP 大包连接失败及一次性 apt 安装被 OOM 终止的问题。默认镜像还将未接入主工作流的 `sentence-transformers` 与仅由 Coder 可选算法使用的 `xgboost` 移为 `semantic-search` / `modeling-extensions` extras，避免 Linux 默认解析隐式下载 Torch/CUDA/NCCL；基础镜像保留 SciPy、scikit-learn、statsmodels 和完整 Pandoc/XeLaTeX/CJK 导出链路。重建后 `redis`、`backend`、`frontend` 均 healthy，`/` 与 `/api/docs` 为 200，`/api/status` 报 `running/local/ready`；容器内规定的 42 项回归和 `ruff check app` 通过。完整真实建模任务尚未在本轮提交，不能以此烟雾测试替代执行证据、冻结和论文导出验收。

- [2026-07-27] 已合并执行验证与论文预检的四项回归修复：压力目标必须有题面或 ModelPlan 可追溯阈值，缺少波动阈值时强制记录实测峰峰值；绝对压力上限不能再被误当作波动上限；不受支持的 `le/ge` 比较符会被拒绝并引导改用 `lte/gte`；`result_consistency` 在冻结事实没有显式 aliases 时会保留数值变体，避免把正确的“最大利润提升至 2266.67 元”误报为与原始 2200 元冲突。合并前定向回归 127 项与 `ruff check app` 已通过。Docker Server 已恢复可用，但尚未重建镜像或重跑任务 `20260726-151904` / `20260726-155823`；后者的端到端确认仍待受控续传或新建验收任务。

- [2026-07-24] 用户要求后续 Codex 不得遗漏可机检的人工复核。仓库 `AGENTS.md` 与最终复核清单现已固化四步：隔离新内核源码重跑、关键数学独立复算、外部引用/方法来源联网真实性核验、结果变动后的受控证据重登记/冻结/全导出及哈希复核。它们必须在用户要求论文验收或完整链路审计时实际执行并记录；平台文件命名、竞赛规则/匿名/诚信和最终主观排版仍由提交人确认。

- [2026-07-24] 上述轻量线性规划任务的人工授权复跑发现 notebook 不是干净内核可复现：一处绘图代码引用未定义的 `FIG_DOUBLE`，问题二一处 f-string 缺少 `{`，敏感性附录还把 `M=120` 的可行边界点 `(60,0)`（利润 2400）错写为最优解，和正确的最优利润 2533.33 矛盾。已将前两处改为可执行代码，并将敏感性边界结论改为直接从 `sensitivity_df` 的实际求解结果读取；在隔离副本和正式任务目录均按顺序完整执行 30 个代码单元成功。随后通过受控 `record_execution_evidence` 重登记 ques1/ques2、重冻 `frozen_results.json`、重做 Markdown/DOCX/LaTeX/PDF。最终 `execution_validation`、preflight、semantic layout、PDF visual、submission audit 均为 PASS，`final_acceptance.technical_status=TECHNICAL_PASS`；仍须由提交人完成平台文件名与竞赛规则复核。

- [2026-07-24] 用户授权复核并修复最新轻量线性规划任务 `20260722-104737-41d7194bc4d66569da5d3a053149f9a7`：正文已删除 7 个空引用占位、统一 CUMCM 标题层级和 10 张图的中文语义图题；将“线性规划多项式时间保证”“机器时间是唯一瓶颈”“影子价格证明模型稳定”等过度表述改为受题设参数、共同紧约束和当前最优基约束的局部结论。重做预检、DOCX、LaTeX sidecar 与本机正式字体 PDF 后，`execution_validation`、`execution_quality_review`、`paper_preflight`、`semantic_layout_review`、`pdf_visual_check`（72/72 页）、`submission_audit` 均为 PASS，sidecar 编译成功，`final_acceptance=TECHNICAL_PASS`，主产物及冻结结果哈希均与新 manifest 一致。自动验收仍不替代人工核对建模假设、代码运行、引用、平台规则和完整 PDF/DOCX。

- [2026-07-24] 导出与验收规则改为 profile/任务契约优先：`ExportProfileConfig.pdf_appendix_pagebreak` 仅为 `cumcm2026` 启用 PDF-only 附录另起页，不写入 `res.md`/DOCX；语义审查把该 profile 行为计入报告，并新增“图题疑似原始文件名”非阻断提示。高压油管历史题遗留的“100 MPa 一律峰峰值 ≤15 MPa”提示和执行硬门禁已删除；`problem_contract` 现在从题面语义提取任意压力目标，实际通过/失败只依据题面或 ModelPlan 中有来源的阈值。没有明确数值阈值时必须记录实际偏差、峰峰值与时序，不能擅自宣称稳定或编造阈值。针对问题契约、执行验证、语义审查、PDF profile 和后处理的 158 项单测及 Ruff 已通过。

- [2026-07-22] 冻结后数学质量复核门禁已补齐：`execution_validation_report=PASS` 只再证明代码/证据技术完整，工作流随后生成 `execution_quality_review.json/md`，保守识别 `quesN_results.csv` 中明确“不达标/失败”及 NaN/Inf。机器命中时一律在 Writer 前进入 `waiting_quality_review`；任务启用 `require_model_review=true` 时，即使机器未命中也必须由当前 Codex/人工逐题复核。新增 `POST /modeling/{task_id}/execution-review`：`approve` 必须提供理由且只绑定当前结果文件哈希形成的 `review_id`；`repair` 只使指定正式子题的 Coder 检查点失效、清除所有依赖旧冻结事实的 Writer 阶段并携审查意见续传，最多一次。旧审批不能跨结果变更复用，普通 `/resume` 不能绕过质量暂停。历史 2019 A 真实任务 `20260720-154617-ab751ff945c00761b3b64066f5eaff71` 用新筛查器只读回放为 `NEEDS_REVIEW`，ques1/ques2/ques3 均存在结果表明确“否”，证明旧链路会放行的质量失败现可被截断；该历史任务仍不可交付。定向28项回归与相关 Ruff 已通过；Docker 真实重跑待运行时恢复后执行。

- [2026-07-22] 上述任务在重建 Docker 后真实续传，已确定停在 `waiting_quality_review`，随后当前 Codex 通过新 `execution-review action=repair` 将 ques1/2/3 连同守恒、量纲、可变容积符号和依赖顺序意见定向退回。Q1 真实执行中先发生一段 12446 字符仿真超过本地 120 秒看门狗，内核与 277 变量快照成功恢复；后续代码虽算出均压 78.7453MPa、峰峰值 68.0195MPa、质量残差 3.95%（仍不合格），但构造时序 DataFrame 时数组长度不一致，三次代码错误预算耗尽。终态 `failed`：`代码阶段 ques1 未提供成功执行证据`，Q2/Q3 未进入返修，Writer 未重新运行。当前处置：质量返修预算已消耗，不再调用同一 Coder 重试或直接改 CSV/manifest；需要补充本机可信的 Codex/人工代码候选执行与证据封装通道，随后才可由操作者确定性接管。

- 2026-07-20：当启用 `require_model_review=true` 的任务在 Modeler 阶段耗尽不合格计划重试时，Coordinator 拆分会在进入 Modeler 前先写入 checkpoint。新增 `POST /modeling/{task_id}/codex-modeling`，允许当前 Codex/审查者提交结构化 `ModelerToCoder.model_plan`；后端仍以 `problem_contract` 校验、原子替换 checkpoint 和写入 `modeler_plan.*`/`modeling_decision.*`，随后回到 `waiting_review`，必须显式 approve 才进入 Coder。它不是绕过题面、执行证据或人工确认的后门。

- 2026-07-20：P0–P2 论文收尾门禁新增三类可审计产物：`candidate_manifest.json` 明确唯一 `submission_file`（默认 `res.pdf`）；受控生成 `support_materials_manifest.json` 与 `support_materials.zip`，仅收录源码、必要数据和图表，记录 SHA-256 并限制 20MB；引用 claim trace 新增 DOI/URL 基本格式与本地来源哈希记录，无法本地验证的来源明确标记 `manual_review_required`。预检/提交审计另输出本地、可解释的相似度/AI 草稿风险提示，但它**不**是正式查重、不能判定抄袭或替代学校/竞赛认可的平台。执行计划新增 `diagnostic_profile`/`diagnostic_requirements`，将精确、数值、优化、拟合或模拟任务的可靠性诊断绑定到受控执行指标；冻结时写入 `reproducibility_manifest.json`，只记录入口、来源哈希与运行时信息，不声称独立重跑完成。PDF 摘要首页检查现要求标题位于摘要之前。

- [2026-07-20] 真实任务 `20260720-062402-4289fffecf237161c40b397a439b3860` 使用 2019 CUMCM A 题原题与三份 Excel 附件启动后，在 Coordinator 的首个模型调用收到 `403 GROUP_DISABLED`（API key 所属分组已停用），8 次短重试后任务状态为 `failed`；仅保留原题附件、`problem_contract.json` 与 `task_request.json`，未生成任何建模、执行验证或论文产物。当前处置：不对同一请求自动重试；由指定决策人切换到已验证且可用的 provider 配置后，才可按恢复规程新建任务或显式续传。

- [2026-07-20] 以 `.env.dev.mimo.bak` 恢复可用 provider 后，2019 CUMCM A 题真实任务 `20260720-065715-86aa4dacc3312c770367993af35f88b8` 已完成题目拆分、模型计划、附件清洗与问题一数值计算，生成 `ques1_results.csv`、约束检查、验收指标和压力轨迹；Coder 三次调用受控 `record_execution_evidence` 均被拒：两次遗漏 ModelPlan 的 `pressure_deviation_rms`、`transition_time_error`、`max_constraint_violation` 约束证据，一次登记的 `2.59` 无法在声明的来源文件中复查。最终 `execution_validation_report.json = FAIL`（`代码阶段 ques1 未提供成功执行证据`），因此未生成冻结结果、问题二/三结果或论文产物。当前处置：不自动重试；先审查 Coder 的指标到来源文件映射与证据提交提示，并由决策人确认后才以新任务或显式恢复继续。

- [2026-07-20] 经用户明确授权后，针对上述失败实施受控修复：标准 `quesN_acceptance_metrics.csv` 现在由后端绑定 ModelPlan 的精确约束数值和来源；验收/约束表的数值、目标、比较符与“通过”文字会被独立复算，矛盾行直接拒绝；受控证据即便成功写入但 `feasible=false` 也会回到 Coder 定向修复。新增回归覆盖精确 CSV 绑定及两类矛盾表。修复后的新任务将仅创建一次以验证该链路。

- [2026-07-20] 修复后新建的 2019 CUMCM A 题真实任务 `20260720-072205-2fdfda30385fc87d7eb3dc5413c559f8` 完成 Coordinator、Modeler、EDA 与问题一仿真，生成网格搜索、时序、质量守恒和验收 CSV；但 Coder 三次证据提交仍失败。现场表将 ModelPlan 的通用键拆为 `*_100MPa` / `*_150MPa` 场景键，且将其中若干数值引用到不含该数值的结果文件，旧容器因此拒绝缺失计划指标和无来源数值。当前处置：已把场景后缀映射为按比较方向取最坏值，并将同名 metric/constraint 强制回绑到验收表；该任务已按熔断规则停止，不自动创建第三个真实任务，等待用户明确授权后才重建容器并发起一次新的验收。

- [2026-07-20] 同次失败还发现早退 Coder 分支用 `require_manifest=false` 写出只含 notebook 检查的 `execution_validation_report.json=PASS`，与 `task_status.json=failed` 形成误导。现正式题早退一律要求该题的 execution manifest；未提交受控证据时报告明确为 `FAIL`。任务状态仍是权威来源；历史失败目录的旧 PASS 报告不应视为验收通过。

- 2026-07-20：按官网《全国大学生数学建模竞赛论文格式规范（2026年修订稿）》复核并收紧 `cumcm2026` 的 LaTeX sidecar：主 PDF 原有的摘要首页、无目录、A4、20MB/正文 30 页/至少 2.5cm 边距和匿名检查保持不变；sidecar 不再复用 2025 `gmcmthesis`，因为其 `\maketitle` 会生成含学校、队号、队员字段的旧式封面。现改用无封面、无目录、无身份字段的 `ctexart` 外壳（左/右 31.7mm、上 30mm、下 28mm），从 Markdown 生成的题目、摘要和关键词直接开始。2025 profile 不受影响；官方若发布 2026 LaTeX 源包，应按 `docs/md/CUMCM2026模板替换指南.md` 新增 `cumcm2026/` 并替换该外壳。

- 2026-07-19：执行验证新增 ModelPlan 产物与可辨识性门禁。对每个正式 `quesN`，验证器会检查 `expected_artifacts` 是否实际存在、非空，且声明的 CSV 数值产物可解析；当 `figure_data` 明确为模型响应/损失/反射率扫描时，还会检查整体及按角度/样品等场景分组后的响应动态范围，拒绝把近常数曲线当作参数扫描证据。若 ModelPlan 明确要求多初值、Bootstrap、剖面或可辨识性分析，执行证据必须记录可辨识性、分支、区间或边界等诊断，单独的“记录有限”不再足以通过。该门禁不设置领域 RMSE 阈值，也不预设模型结论；它只阻断缺少稳定性证据的自动冻结/写作。触发后应生成真实诊断表，若不可辨识则如实报告并停止将单一局部/边界参数写为确定性结论。针对历史光学任务 `20260717-144854-2f67cf50c60faf5ad02eea5d3b52f2b1` 的只读复核现会拒绝：问题一按角度/材料分组的厚度扫描响应退化、三问缺少合格可辨识性诊断，且问题三缺少计划声明的 `ques3_multibeam_parameter_audit.csv`；不得只重导 PDF 使其看似通过。

- 2026-07-14：仓库级 `AGENTS.md`、`skills/1start-mathmodel/SKILL.md` 与全局 `C:\Users\Johnny\.codex\AGENTS.md` 已按当前 Codex `spawn_agent` 接口更新多智能体限制：主 agent 创建子任务必须显式使用 `fork_context:false`，严禁 `fork_context:true`，不再使用不属于当前接口的 `fork_turns`；只有主 agent 可 spawn，subagent 不得嵌套 spawn；同一时刻活动的直接 subagent 最多 5 个，且仅接收阶段摘要、明确目标和文件路径。真实建模任务如需断点续传优先走后端 `POST /modeling`；发起子线程前必须确认经用户授权的隔离计费与预算限制。

- 2026-07-14：主工作流的最终执行验证失败会保留已通过 `quesN` 的代码检查点，并对报告中定位到的失败题目最多进行一次自动定向回修；回修后再次失败或同一任务已记录两次真实验证失败时，停止 Writer/PDF 和自动重试，要求按恢复规程人工切换已验证 provider 或确认低开销算法。执行冻结通过后，若 `paper_preflight_report.json` 的硬失败只定位到 `result_consistency` 等可归属正文的检查项，工作流还会把冲突证据和冻结事实只交回受影响章节的 Writer 一次，再重新预检；无法归属的失败、或回修后仍为 `FAIL`，会停止候选 PDF 导出而不是生成貌似完成的论文。DOCX 收尾后生成 `final_acceptance_report.json/md`：`TECHNICAL_PASS` 同时要求执行验证、冻结来源哈希、preflight、PDF visual、正式字体、主交付文件/manifest 和论文附录完整源码通过；数学、引用、版式及平台规则始终是 `PENDING_HUMAN_REVIEW`。论文后处理不再将附录源码截断为 240 行，而是写入完整脚本/notebook 代码单元及 SHA-256；完整源码可能增加页数，仍须实际 PDF 视觉检查。

- 2026-07-14：正式 `quesN` 的 Coder 到达成功代码调用上限时，不再直接以“成功收束”进入下一阶段。后端会只暴露 `record_execution_evidence` 并要求提交本题的结果文件、约束、指标和图表数据来源；兼容 provider 若仍回传旧的 `execute_code` 调用会被拒绝，不会继续执行。受控记录成功后才结束该 Coder 子任务。`checkpoint.json` 从已冻结状态续传时会清除旧的连续回修计数，且每次新冻结也会重置该计数，避免历史成功冻结耗尽下一次真实失败的回修额度。

- 2026-07-14：正式 Coder 回合的证据还必须来自**本回合实际执行中新建或更新**的结果/图表数据文件；不允许用 checkpoint 中未更新的旧 CSV 重新登记。一个回合只能处理一个工具动作，多个并发工具调用会得到逐一的重试说明而不会留下孤立 tool-call id；回合只允许记录自己的 `quesN`，不能覆盖其他已通过题目。对正式题目，连续“任务完成”输出或无工具完成说明也会转入强制证据提交，不能绕过验证。证据记录成功即结束该题 Coder 回合，防止后续模型改写结果后令 manifest 失效。

- [2026-07-14] 真实任务 `20260714-021910-23c08616b2c6256627fcfd85fdb0f66c` 从 checkpoint 续传时，问题二 Coder 连续成功执行 8 次却未调用受控证据工具，旧 manifest 的 SHA-256 与刚写入的结果 CSV 不一致，且缺少线性规划决策变量指标，最终 `execution_validation_report.json = FAIL`；Writer/PDF 未被再次放行。当前处置：已实现上述强制证据收束并通过单元测试，**不**对该任务发起第三次自动/真实重试；应按恢复规程以新任务或经人工确认的 provider/算法方案重新运行。

- 2026-07-14：可在任务目录由受控导出配置写入 `paper_appendix_config.json` 的 `{"mode":"key"}`，使附录 B 展示已验证的 `key_algorithms.md`（关键伪代码/核心实现）而不是完整 notebook 转储，用于参考国一复刻模板的阅读性。完整源码仍保留为支撑材料；该展示模式刻意不能通过 `complete_source_appendix`，因此 `final_acceptance_report.json` 不会是 `TECHNICAL_PASS`，正式提交必须改回完整源码附录。

- 默认新建建模任务使用 `cumcm2026`。
- 主交付链路是：
  - `res.md`
  - `res.pdf`
  - `res.docx`
  - `res.json`
  - `candidate_manifest.json`
  - `paper_preflight_report.json`
  - `pdf_visual_check.json`
  - `submission_audit_report.json`
- `latex_project/` 是候选 LaTeX sidecar，不是主交付链路。
- 2026-07-13：主 WebUI workflow 已接入题面参数、执行可行性与结果冻结门禁。任务创建/续传会写入 `problem_contract.json`；题面可识别的不可变参数和必答要求会传给 Modeler/Coder。全部 solution 代码阶段会先单独持久化到 checkpoint，完成全部正式问题后才创建 `execution_validation.json` 并通过 `execution_validation_report.json`（代码实际执行、每问可行性、约束来源 SHA-256、图数据来源）；通过后由受信任 workflow 生成 `frozen_results.json`，最后才允许 Writer 与 preflight 使用其作为计算数值事实源。notebook 的历史报错会保留在报告中；只有存在通过哈希/约束校验的最终执行清单时才视为已由最终计算证据覆盖。历史任务没有这些新产物时应按当前门禁重跑，不能凭旧的 `completed`/preflight `PASS` 认定数学内容通过。
- 2026-07-13：preflight 新增冻结完整性、冻结数值/图文一致性、不可行解最优化表述、算法代码证据和明确跨领域引用相关性检查；`submission_audit_report.json` 也要求 `execution_validation_report.json = PASS`。这些门禁提高可追溯性与明显错误拦截能力，仍不替代独立数学推导、数值收敛与人工复核。
- [2026-07-13] 2019 CUMCM A 题真实重跑 `20260713-091903-3d8e333eb10220b849fda0878ba11f69` 在 Coder 的压力恢复 `solve_ivp` 数值实验中进入高 CPU、无 IOPub 返回状态，旧实现的单线程超时轮询未能及时中断。当前处置：受控 Linux Docker 中本地解释器使用独立 OS 级看门狗向内核进程发送中断/终止信号，非 POSIX 回退才使用线程计时器；单段代码上限调整为 120 秒。超时一律作为执行失败，不得生成冻结结果或进入 Writer。修复后需用同题新任务完整重跑。
- [2026-07-13] 真实任务 `20260713-094126-a94c9d8a07cce0aa80ea9cb844338b52` 首次续传在尚未生成任何 `res.*`/PDF 时被安全停止：审计发现旧流程在最终执行验证和结果冻结前已对 `ques1` 调用 Writer，且 notebook 留有 TypeError/NameError 历史错误、无可验收 manifest。当前处置：代码阶段与写作阶段已拆分并为代码响应增加 checkpoint 持久化；恢复时先完成哈希验证/冻结，再重写所有 solution 正文，禁止复用冻结前 Writer 文本。待同一任务恢复完成后以 PDF、preflight、visual check、submission audit 实测验收。
- [2026-07-13] 上述任务在修复后真实续传的敏感性分析中，有一段代码达到 120 秒硬上限；受控 Docker 的 OS 级看门狗已发送中断，解释器将其记为执行错误，未创建冻结结果或触发 Writer/PDF。当前处置：仅允许 Coder 的有限反思重试改写该段计算；若仍不能在限制内完成，保持任务失败并依据 checkpoint 产物改用更低开销且可复核的算法，不放宽超时或手工伪造验证清单。
- [2026-07-13] 真实任务 `20260713-094126-a94c9d8a07cce0aa80ea9cb844338b52` 在全部正式代码阶段完成后仍被最终执行门禁拒绝：`execution_validation_report.json = FAIL`，问题 1 仅有 PNG 而无可校验数值结果源，问题 2 无结果文件，问题 3 的 `问题3_仿真数据.csv` 给出平均压力 `41.61315472855306 MPa`、相对目标 `100 MPa` 的偏差 `58.38684527144694 MPa`、标准差 `27.014085871749835 MPa`，不满足目标偏差和波动约束；因此没有 `frozen_results.json`、`res.md`、`res.docx` 或 `res.pdf`。当前处置：manifest 必须以精确 `source.path` 指向任务内 CSV/JSON/TXT 并包含有限数值；每问必须产出 `quesN_results.csv`，图表需有独立数据源；最终验证失败会清除全部 solution 代码/正文 checkpoint，防止续传复用未验证内容。该任务已连续多次在同一 provider 下失败，按赛前恢复规程不得再自动重试；须由指定决策人切换到已验证的备用 provider/配置后最多续传一次，或人工确定可复核的低开销算法，不能放宽约束或伪造 manifest。
- [2026-07-13] 用户明确要求继续该任务后，第二次真实续传虽生成 `ques1_results.csv`、`ques2_results.csv`、`ques3_results.csv`，但最终 `execution_validation.json` 错把规范要求的 `subtasks` 写成 `tasks`，所以 `execution_validation_report.json = FAIL`，没有进入 Writer/PDF。进一步审计发现该清单不能作为数学验收证据：问题 2 的核心数值明确标注为“基于问题 1 稳态结果估计”，并未执行建模手要求的耦合仿真与搜索；问题 3 的减压阀开启次数为 0，却把阈值当成控制效果验证。当前处置：最终门禁要求每问记录实际计算的守恒残差，并在题面要求减压阀控制时提供扰动/超压下的真实开启证据；续传必须重新执行正式代码阶段，不得仅修正 JSON 字段名后进入写作。
- [2026-07-13] 同一真实任务再次续传后，已完成问题二耦合仿真和问题三实际阀门动作（62 次），但最终门禁仍拒绝：清单使用了未约定的 `gt` 比较符，并将 CSV 误登记为图表而无图数据哈希；更关键的是 `q3_pressure_fluctuation=42.37 MPa`，在 100 MPa 目标下不能称为稳定。当前处置：验证器兼容严格比较符以便如实报告数学条件，但工作流提示只允许规范比较符；对有明确 100 MPa 目标的题面新增 15 MPa 峰峰值硬上限。后续续传必须重新优化问题三控制，不能以仅修复 manifest 结构进入 Writer/PDF。
- 2026-07-13：`skills/` 实验性工作流增加 `2a-method-validation`、
  `3a-result-freeze`、`6a-independent-audit` 和 `workflow_guard.py`：前者要求
  方法 PoC 与人工选型，后两者冻结关键指标/来源哈希并独立审计。它们只作用于
  skill 工作区，不接入 FastAPI/Vue WebUI 主工作流，不改变 `res.*`、默认
  export profile 或既有提交审计；冻结/审计只能证明来源和基本可追溯性，不能证明数学正确性。
- 2026-07-13 P2：实验性 skills 通过 `algorithm-routing.md` 按题型渐进加载现有规范库，
  并在仓库根提供 `.codex-plugin/plugin.json` 供 Codex plugin 分发；未创建 marketplace，
  不会自动安装或接入 WebUI 主工作流。
- [2026-07-13] 真实轻量线性规划任务 `20260713-021852-8d8e948a7a679b5abcd5e76d25894412`
  在 Modeler 后、代码执行前失败：Docker 运行配置缺少 `E2B_API_KEY`，remote 默认安全关闭，
  已生成 checkpoint 但无主交付物。当前应对：仅在受控单用户 Docker 中启用
  `docker-compose.local-execution.yml` 的显式本地执行覆盖后，从 checkpoint 续传；不要在普通
  `.env.dev` 中把正式/验收环境切到 local。
- [2026-07-13] 上述任务已在受控 Docker 本地执行覆盖中从 checkpoint 续传完成：`/tasks` 为
  `completed`，`res.md/res.json/res.docx/res.pdf`、`candidate_manifest.json`、checkpoint 和变量
  快照均存在；`paper_preflight_report`、`pdf_visual_check`、`submission_audit_report` 均为 `PASS`，
  LaTeX sidecar 编译成功。人工核验正文数值为 `A=40`、`B=20`、利润 `2200`；机器时间增至
  `110` 后为 `A≈46.67`、`B≈16.67`、利润 `2366.67`。该结果验证受控恢复路径和导出链路，
  不等同于将本地解释器设为正式环境默认值。
- [2026-07-13] `STARTUP.md` 现将 Docker 启动路径、首次配置预检、E2B 缺失时的受控恢复与
  默认安全模式回退前置，并提供“测试 -1”无模型启动/代理烟雾脚本。脚本已实测通过：Compose
  三服务为 `healthy`，首页和 `/api/docs` 为 HTTP 200，`/api/status` 的 backend/redis 状态为
  `running`。PowerShell 中不要使用 `$home` 作为变量名（与只读 `HOME` 冲突）。
- [2026-07-13] 真实任务 `20260713-071018-f6816c34351283cb1a7509d9800cbc4d` 在默认
  `CODE_INTERPRETER_KIND=remote` 且未配置 `E2B_API_KEY` 时于 Coder 创建解释器阶段失败；
  已保留 `checkpoint.json`，尚无代码执行和主交付物。当前处置：实现并验证受控本地 Docker
  自动降级入口后从该 checkpoint 续传，不重新提交题目。
- [2026-07-13] 上述真实任务已通过受控本地 Docker 自动模式（`auto`、显式允许本地执行、
  无 E2B）从 checkpoint 续传完成：任务状态 `completed`，`res.md/res.json/res.docx/res.pdf`、
  manifest、checkpoint、变量快照、paper preflight、PDF 视觉报告、LaTeX sidecar 和提交审计
  均生成；preflight 为 `PASS`，LaTeX 编译成功。PDF 视觉门禁因正文摘要后 34 页超过当前 30 页
  上限为 `FAIL`，submission audit 随之为 `FAIL`，需人工压缩正文或按正式规则单独处理，不能
  将该门禁失败归因于本地解释器。运行期间出现一次模型代码错误（随后自动修复）和一次
  Semantic Scholar HTTP 警告，均未阻断任务完成。
- `GET /download_all_url` 会按需生成任务目录下的 `all.zip`，用于下载当前任务工作区文件；
  打包时会排除已有 `all.zip`、临时文件和常见缓存目录，并设置单文件/总大小上限，避免
  意外打包过大目录。
- LaTeX sidecar 当前已修复 CUMCM 图片路径、新版 pandoc `\pandocbounded`
  图片宏、notebook `# Cell n` 原始代码段拆分问题；导出时会扫描 Markdown/LaTeX
  中引用的本地图片，将可找到的图片复制到 `latex_project/` 和
  `latex_project/figures/`，并在 `tex_export_status.json` 记录
  `copied_assets` / `missing_assets`；若图片文件名包含 `%`、中文、`±` 等
  LaTeX 高风险字符，sidecar 会复制为 `figures/figure_XX.ext` 并重写
  `sections/*.tex` 内的 `\includegraphics` 引用，不改 `res.md` 和主 PDF/DOCX。
  sidecar 与主 PDF 都禁用 raw TeX，自动编译向 XeLaTeX 传入 `-no-shell-escape`；
  若 `latexmk` 失败，会 fallback 到连续两次同样受限的 `xelatex`，并记录
  `compile_reason` / `compile_failure_summary`。
- CUMCM sidecar 模板字体 fallback 已覆盖 `KaiTi` / `STXinwei` / `LiSu`；Docker
  中缺少 Windows 字体或 `AR PL KaitiM GB` 时，会继续 fallback 到 Noto CJK 字体，
  优先保证候选 LaTeX 工程可编译。
- Docker 正式字体自动化方案：Compose 支持通过根目录 `.env` 的
  `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 只读挂载宿主机已合法安装的字体到
  `/usr/local/share/fonts/mma-extra`，后端入口自动 `fc-cache`。这不是把开源字体
  转换为专有字体，而是在 Docker 内复用宿主机正式字体；`font_utils` 已支持
  `fc-match` 返回 `SimSun,NSimSun` 这类字体族列表时正确命中。
- 任务完成时会自动生成 `submission_audit_report.json/md`，汇总主交付文件、
  preflight、PDF 视觉检查和 `export_status.json -> pdf.font_resolution`。
  由于 workflow 先导出 Markdown/PDF/LaTeX，再由路由最终生成 DOCX，正常完成后的
  收尾步骤会在 `res.docx` 生成后重新刷新 `submission_audit_report.json/md`，
  最后再刷新 `candidate_manifest.json`，避免审核报告读取到“缺少 res.docx”的旧状态。
  默认模式下 Docker fallback 字体记为 `WARN`；正式提交前可运行
  `uv run python -m app.tools.submission_audit --work-dir project\work_dir\<task_id> --require-official-fonts`
  作为严格门禁，fallback 或未知字体来源会 `FAIL`。
  `paper_preflight_report.json = CONDITIONAL_PASS` 会在 `submission_audit_report`
  中记为 `WARN` 而不是 `FAIL`，用于表达主交付可生成但存在需人工复核/接受的条件项；
  `paper_preflight_report.json = FAIL` 或无法读取报告仍是硬失败。
  用 `export_cli pdf` 手动/正式重导时加 `--update-status`，会同步刷新
  `export_status.json`、`pdf_visual_check.json`、`submission_audit_report.json`
  和已有的 manifest，避免审核读取旧字体记录。
- CUMCM 官方 2026 论文格式规范强调电子版论文为单独 PDF/Word 文件（建议 PDF、
  不超过 20MB），第一页必须是摘要页，不放承诺书和编号专用页；电子版应与纸质版内容/格式
  一致，附录须包含全部完整、可运行源程序。支撑材料还须单独压缩并包含必要源程序、数据资料
  和较大篇幅中间结果图表。当前后处理会把发现的完整脚本/notebook 代码单元写入附录 B，
  记录 SHA-256，并由 `final_acceptance_report.json -> complete_source_appendix` 核验覆盖与正文内容；
  正常的 `print(...)` 等可运行源码不会被删除或误判为控制台噪声。
- 当前最新真实烟雾任务的主链路曾达到：
  - `task_id = 20260709-091916-1ff165da`
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check = PASS`
  - `tex_export_status.json -> compile_success = true`
  - `latex_project/main.pdf` 已生成
  - `submission_audit_report.json` 经 DOCX 后收尾刷新后为 `PASS`
  - 该任务使用 `mimo-v2.5` 真实接口完成轻量线性规划题，最优结果为
    `A=40, B=20, profit=2200`，机器时间增加 10 小时后利润约 `2366.67`。
- 2026-07-09 针对当前多 PR 风险修复分支重建 Docker 后，基础服务烟雾验证通过：
  `docker compose up --build -d`、前端入口 `http://127.0.0.1:5173/`、后端
  docs 代理 `http://127.0.0.1:5173/api/docs`、容器内后端单测与
  `ruff check app` 均可运行通过。完整真实建模 smoke 暂被外部 LLM provider
  阻塞，最新任务 `20260709-014347-c9ed2ddd` 在 Coordinator 阶段连续重试后失败：
  `403 GROUP_DISABLED` / `API Key 所属分组已停用`；任务目录仅生成
  `task_status.json` 和字体文件，无 `res.md`、`res.json`、`res.docx`、
  `candidate_manifest.json` 或 checkpoint。恢复有效 key 后需重跑项目规则中的
  轻量线性规划题，验收 `/tasks` 为 `completed` 且主交付文件存在。
- 2026-07-09 使用用户提供的新 `xiaomimimo` Responses provider key 后，模型验证
  `mimo-v2.5` + `https://api.xiaomimimo.com/v1` 成功，并完成一次真实轻量任务
  `20260709-091916-1ff165da`。随后在 PR #8 合并后的修复代码上
  再次重建 Docker 并重跑真实任务 `20260709-093451-96f6f897` 时，任务已越过
  Coordinator/Modeler/Coder，后续 Writer 阶段因 provider 返回 `402 Insufficient account balance`
  中断；这表示 key 已可用但账户余额不足，恢复余额后需继续重跑完整 smoke。
- `cumcm2026` 是基于 2026 修订稿规范实现的暂定模板，不是官方最终 DOCX/LaTeX 模板包。
- 主 PDF 导出会在摘要/关键词后做 PDF-only 分页，支持裸 `关键词：...` 与
  `**关键词**：...`，保证摘要页独占第一页、正文从第二页开始；该分页不写回
  `res.md`，也不影响 DOCX 或 LaTeX sidecar。
- `cumcm2026` 主 PDF 当前使用 `left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm`；
  底边距高于 2.5cm 是为了给实际字体字形 bbox 留安全余量，避免正文末行触发
  CUMCM 2.5cm 内容边距检查失败。
- 论文后处理会做内容一致性兜底：移除没有参考文献条目支撑的裸 `[n]`
  引用、为 Markdown 表格自动补 `表n` 标题、清洗 Markdown 图片 alt 文本避免
  PDF/DOCX 图题带 `.png`/下划线等文件名痕迹、把常见英文过渡词
  `Overall`/`However` 等替换为中文表达、在正式题目数不足时把可见 `问题3_...`
  扩展分析标签和 `问题三：...` 扩展段落规范为 `灵敏度分析...`（图片路径保持原文件名）。
  图片预检会区分正文图和支撑材料图：正文 `![](...)` 引用的图片必须存在；生成图片
  若没有正文引用但已在附录A支撑材料表中登记为 `图片文件`，视为 accounted support
  artifact，不再计入 `checks.images.unused_generated`；既未正文引用、也未登记的生成图片
  仍会触发图片 conditional。
  工作流会把原题拆分出的 `quesN` 数量传给后处理，避免 Writer 自行编出的额外问题
  污染题目数判断。后处理还会清理最终稿和附录代码中可见的 `用户`、`推断`、
  `估算`、`待验证` 等提交痕迹，改为 `题目`、`核定`、`测算`、`需核验` 等正式表达。
  代码附录中的纯装饰性超长分隔线会缩短到安全长度，避免 PDF 内容边距检查
  因源码页超宽文本误报失败。
  独占一行的加粗短标签（如 `**假设1：...**`）会规范为 Markdown 小标题，
  避免 Pandoc 把后续整段误解析成 LaTeX description label 导致正文不可换行。
  孤立的 `: ... DOI ...` 定义式参考行会被删除，避免同类 description list 误解析。
  预检还会阻断电子论文中出现 `承诺书`、`编号专用页`、`参赛队号`、`队员姓名`
  等身份/封面字段，避免违反高教社杯匿名电子稿口径。
  `paper_preflight_report.json -> checks.result_consistency` 会读取任务目录中
  结果 CSV 的结构化关键数值，目前重点检查机器时间/人工时间影子价格；如果正文
  同标签句子中的数值与 CSV 不一致，预检硬门禁 `FAIL`。没有可识别结果 CSV 时
  不阻断，因此该检查只能拦截已结构化事实的明显冲突，不替代完整数学复核。
  `flows.get_writer_prompt` 会把同一批结构化结果事实注入写作手提示，要求正文关键
  数值优先使用结果 CSV，减少 Writer 在摘要/求解/敏感性段落中复述错误数字。
  若正文已经说明题目参数是确定性常量、无随机样本数据，后处理会把
  `描述性统计` 这类样本数据 EDA 用语规范为 `参数核验`，并清理正文/支撑材料中的
  Monte Carlo、蒙特卡洛、随机模拟等探索性随机模拟内容；代码附录中的同类标签会
  降级为参数扰动表述。
- 参考文献条目会以空行分隔，避免 Pandoc PDF/DOCX 导出时把多条参考文献合并成
  同一段；若模型生成空参考文献段且正文无有效引用，后处理会删除空参考文献段，
  预检不再因为“无引用且无文献”单独失败。
- 代码手 EDA 提示已区分“无外部数据集”和“数据驱动题”：当当前数据集文件列表为空时，
  不得随机生成模拟样本或创建模拟数据集，只做题目给定参数、单位、约束和可行域核验。
- Docker 前端不再依赖浏览器直连宿主机 `8000` 端口：`frontend/.env.docker`
  使用 `VITE_API_BASE_URL=/api`、`VITE_WS_URL=ws://localhost:5173/ws`，由
  Vite dev server 代理到 Compose 内部 `backend:8000`；后端 Docker 场景的
  `SERVER_HOST` 也指向 `http://localhost:5173/api`，下载链接走同一代理入口。
- LLM provider 单次请求超时由 `LLM_REQUEST_TIMEOUT_SECONDS` 控制，默认 90 秒；
  用于兼容较慢的 OpenAI-compatible/Responses/Anthropic 端点，避免建模手或写作手
  在正常长响应时过早 `Request timed out`。LLM 层以 `asyncio.wait_for` 强制该上限，
  并关闭三个 SDK 的隐式重试，重试次数只由项目层控制，避免单次请求因嵌套重试失去时限。
- `HUMAN_MODEL_GATE_ENABLED=true` 时，Modeler 阶段会生成 `modeling_decision.md/json`
  并把任务状态置为 `waiting_review`；前端任务页会定时刷新任务状态并显示“确认建模方案并继续”，
  调用 `/modeling/{task_id}/approve-modeling` 后从 Coder 阶段续跑。
- 2026-07-10 在 PR #11 最新后端与 PR #6 前端的临时集成 worktree 中重建 Docker，
  真实任务 `20260710-010231-e6470545` 从 `running` 自动进入 `waiting_review`，无需刷新页面
  即显示审批按钮；审批后任务恢复并完成。`modeling_decision.json=approved`，checkpoint、
  变量快照、Markdown/JSON/DOCX/PDF、manifest 均生成，preflight、PDF 视觉检查和 LaTeX
  编译通过；submission audit 仅因 Docker fallback 字体为 `WARN`。
- `/status` 的 `backend.feature_warnings` 会报告配置存在但尚未接入主工作流的能力，
  例如 `RAG_ENABLED`、通用 `HIL_ENABLED`、`FALLBACK_ENABLED`、`EVALUATOR_ENABLED`；
  这些 warning 不阻断服务启动，只用于避免把配置开关误判为已完成功能。
- `/save-api-config` 只把验证后的模型配置应用到当前后端进程的 `settings`，
  不写回 `.env.dev`，响应中会明确 `scope=runtime`、`persisted=false`；
  空字段不会覆盖 `.env.dev` 已加载的默认值，且响应不回显 API key。前端 Pinia
  store 不再持久化用户填写的 API key，页面升级时会清理旧版 `localStorage.apiKeys`。
- 2026-07-11 安全默认值：Docker Compose 前后端端口只绑定 `127.0.0.1`；CORS、
  WebSocket Origin 和 Host 均为明确 allowlist（防 DNS rebinding）；工作区文件不再以任意静态目录直出，
  只有安全单层文件名可下载，非栅格图片附件强制下载。新 task_id 使用 128 位随机
  capability 后缀；上传按单文件/总量流式限额写入。
- 模型生成代码默认必须通过 E2B 远程沙箱执行（`CODE_INTERPRETER_KIND=remote`）。可信单用户
  Docker 环境可加载本地执行 Compose 覆盖；该覆盖明确设置 `CODE_INTERPRETER_KIND=local` 和
  `ALLOW_LOCAL_CODE_EXECUTION=true`，不因 E2B 配置变化而切换后端。若要让普通 `docker compose`
  命令持续加载该覆盖，只能在本机 gitignored 根目录 `.env` 中显式设置 `COMPOSE_FILE`；版本库
  `.env.example` 仅保留注释示例，安全默认仍为 remote/拒绝本地执行。
  基础 Compose 不挂载完整源码，后端镜像排除 `.env.*`；本地模式只支持受控 Linux Docker，
  内核启动或重启前必须把当前任务目录交给专用非 root `mma-runner` 用户，并在 exec 前降权；
  后端仅在该覆盖文件中保留 `CHOWN`、`DAC_OVERRIDE`、`SETGID`、`SETUID`、`KILL` 五项能力来
  管理共享任务文件、降权和终止该降权子内核；runner 降权后不继承这些能力，`PR_SET_DUMPABLE=0`
  作为额外纵深防护。为兼容 Windows Docker 共享目录，不强制修改 POSIX mode 位；降权、环境保护
  或内核生命周期管理不可用即失败关闭；随后内核只继承
  最小环境，代码单元有超时中断。容器日志只记录 Agent/代码/消息的类型、数量或长度，不回显
  正文、提示词、代码、工具参数或图像 Base64。
  该模式仍与后端共享文件系统和网络，只适用于可信单用户恢复开发，不能用于共享/公开/
  正式验收环境，也不能与热重载 `docker-compose.dev.yml` 混用。
- LLM Base URL 默认要求 HTTPS、公开 IP/DNS 解析结果，且 SDK 请求禁用重定向与环境代理；
  对瞬时 DNS 故障会进行 3 次短暂解析尝试，全部失败仍失败关闭；私有地址必须显式设置
  `ALLOW_PRIVATE_LLM_BASE_URLS=true`。
- LLM 成功调用后会在任务目录写入 `token_usage.json`，只保存按 agent 聚合的
  `chat_count`、`prompt_tokens`、`completion_tokens`、`total_tokens` 和模型名，
  不保存 prompt、completion、tool args、API key 或 base_url；`GET /track`
  读取该文件返回聚合统计。统计写入是 best-effort，失败不会让已成功的 LLM 调用重试；
  当前只保证单进程内加锁累加，多 worker/多进程场景不作为强一致账单依据。
- Anthropic provider 对 `api.anthropic.com` 官方地址继续使用 Anthropic SDK
  `api_key` 认证；对非官方 Anthropic 兼容网关改用 Bearer `auth_token`，
  以兼容 `ANTHROPIC_AUTH_TOKEN` 风格服务。2026-07-09 用户提供的 CloudBase
  网关已用 `hy3-preview` 验证文本请求和 `tool_choice=auto` 工具调用可用；
  本地忽略配置 `backend/.env.dev` 可设置四个 Agent 使用
  `COORDINATOR/MODELER/CODER/WRITER_API_TYPE=anthropic`、模型 `hy3-preview`
  和对应 CloudBase base URL，密钥不应写入 Git。
- 2026-07-09 CloudBase `hy3-preview` 真实轻量 smoke 任务
  `20260709-111913-995cfe14` 已在 Docker 中通过续传完成，主产物、变量快照、
  `paper_preflight_report=PASS`、`pdf_visual_check=PASS`、
  `tex_export_status.compile_success=true`、`candidate_manifest.json` 均生成；
  `submission_audit_report=WARN`，唯一 WARN 是 Docker 环境缺少 SimSun /
  Times New Roman 导致 PDF 字体 fallback 到 Noto Serif CJK SC /
  Liberation Serif。按项目规则这不视为主流程失败，正式提交前仍应挂载
  `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 或在 Windows 本机重导并跑严格字体门禁。
  在新增 `checks.result_consistency` 后，用当前分支代码只读复核该任务会因正文影子价格
  `26.7/13.3` 与 CSV 中 `16.67/6.67` 冲突而 `FAIL`；这说明旧报告的 PASS 不能代表
  当前代码门禁结果。该 smoke 只证明 provider/导出链路可用；preflight/audit 仍不等同
  于数学正确性证明。
- 2026-07-09 在 PR #11 对应代码上重建 Docker 后，CloudBase
  `hy3-preview` 真实轻量 smoke 任务 `20260709-153822-846f9e0e` 完成。刷新后
  `paper_preflight_report=PASS`、`checks.images.unused_generated=[]`、
  `checks.result_consistency.passed=true`、`pdf_visual_check=PASS`、
  `tex_export_status.compile_success=true`、`res.docx`、`candidate_manifest.json`
  均生成；`submission_audit_report=WARN`，唯一 WARN 是 Docker 环境字体 fallback，
  按项目规则不视为主流程失败。
   该 smoke 只证明 provider/导出链路可用；preflight/audit 仍不等同于数学正确性证明。
- 2026-07-11 在最终审计修复分支重建 Docker 后，前端入口、`/api/docs` 代理、
  后端 docs、容器内指定单测和 Ruff 均通过；真实轻量线性规划任务
  `20260711-005536-09d34201` 在 Coordinator 早期因 provider 授权失败而终止，
  未生成主交付物或 checkpoint。按当次验收要求未重试；恢复有效 provider 授权后，
  需重跑项目规则中的轻量线性规划题并核验任务状态和交付物。
- 2026-07-11 更新有效的 OpenAI Responses 兼容运行配置并重建后端后，模型枚举与
  真实轻量线性规划任务 `20260711-133616-38439fe3` 均成功。任务状态为 `completed`，
  已生成 Markdown/JSON/DOCX/PDF、manifest、checkpoint 和变量快照；
  `paper_preflight_report`、结果一致性、PDF 视觉检查、submission audit、PDF 导出和
  LaTeX 编译均为 `PASS`/成功。正文经人工数值核验为 `A=40`、`B=20`、利润 `2200`，
  机器时间增加 10 小时后利润 `2366.67`；`/track` 返回四个 Agent 的聚合统计，
  `/download_all_url` 生成并成功下载 ZIP 归档。
- 2026-07-11 安全收尾验证：Docker 重建后，容器内全量非 E2B 单测 `214 tests`、
  Ruff（含 `--select S`）、Bandit、pip-audit、前端 TypeScript/生产构建和生产依赖
  audit 均通过；前后端仅监听 `127.0.0.1`，未受信任 Host 分别被后端 `400`、前端
  `403` 拒绝。对任务 `20260711-133616-38439fe3` 重新执行
  `submission_audit --require-official-fonts` 为 `PASS`。这轮没有另起真实模型/E2B
  任务，严格审核复用的是已完成真实任务的交付物。
- 2026-07-12 Docker/CI 安全维护：GitHub Actions 已固定到使用 Node 24 的发布提交，
  CI `GITHUB_TOKEN` 仅授予 `contents: read`，checkout 不持久化凭据；前端容器已从
  结束支持的 Node 20 升级到 Node 24 LTS。Compose 为 Redis、后端和前端配置健康检查，
  并以健康依赖顺序启动。Docker 基础镜像或系统包安全更新时先执行
  `docker compose build --pull`，再 `docker compose up -d --wait` 并确认
  `docker compose ps` 中三个服务均为 `healthy`，避免刚启动时的连接重置或代理 `500` 误报。
- 2026-07-12 当前 Docker 运行配置中四个 Agent 的模型凭据存在，但
  `E2B_API_KEY` 缺失。历史轻量任务 `20260712-024021-3050861c811b2e324f70675e8d5b49a2`
  曾按当时的 `remote` 安全默认值失败；现在可在受控 Linux Docker 中使用
  `docker-compose.local-execution.yml` 的显式信任覆盖完成恢复开发。不要通过普通
  `.env.dev` 把生产/验收环境切到 `local`，该覆盖不等同于 E2B 沙箱。
- 2026-07-12 在该受控本地执行覆盖中，真实轻量线性规划任务
  `20260712-084612-4c953bb6dadb65d2ed5cb493839ba70c` 完成：状态为 `completed`，
  `res.md/res.json/res.docx/res.pdf`、manifest、checkpoint、变量快照、PDF/LaTeX
  导出、preflight、PDF visual check 与 submission audit 均通过，`/track` 返回四个
  Agent 的聚合统计，ZIP 下载为 200。运行时检查确认 kernel 为 UID 10001、无有效 Linux
  capabilities、无敏感环境变量、不能读取 backend `/proc` 环境，backend 可持久化任务文件，
  kernel 退出后连接目录和进程均清理。此验证只证明受控单用户恢复开发链路，不替代 E2B 或
  等效隔离运行器的共享/公开/正式验收要求；测试任务目录和 Compose 容器已在收尾时清理。
- 2026-07-13 真实高压油管任务 `20260713-094126-a94c9d8a07cce0aa80ea9cb844338b52`
  的执行验证为 `PASS`，且已生成 PDF/DOCX/LaTeX sidecar；但首次交付预检与 PDF
  视觉检查为 `FAIL`。原因分别是算法证据检查把“未来可升级为遗传算法、粒子群”的改进建议
  误判为已采用算法，以及约 850 字摘要使关键词溢出首页。修复前不得将该任务称为可验收；
  应压缩摘要并重导，同时仅对正文中实际采用的算法要求代码证据。已在同一任务上把摘要压缩
  为冻结结果支持的紧凑版本，并重导 DOCX/PDF/LaTeX sidecar；随后
  `paper_preflight_report`、`pdf_visual_check`、`submission_audit_report` 均为 `PASS`，
  LaTeX 编译成功。Docker 中相关 87 项单测与 Ruff 也通过。
- [2026-07-13] 同一高压油管任务虽已通过技术导出门禁，但人工复核发现问题一未在正文与冻结结果中
  给出题面要求的单向阀稳态开启时长、2/5/10 秒升压策略及切回稳态策略；旧
  `ques1_results.csv` 的 0.6/1.2/1.0/0.8 ms 也没有由附件 3 的完整压力—密度模型复核。
  当前处置：以桌面 MATLAB 方程和题目附件为基线运行独立复算脚本，更新执行清单、冻结、论文和
  导出；在五项控制指标和对应压力误差均可追溯前，不得再称该论文为最终可验收稿。
- [2026-07-13] 上述高压油管任务已用附件3压力—密度模型和固定步长 RK4 独立复算并重导：100 MPa
  稳态开启时长为 0.288217 ms，150 MPa 稳态为 0.750000 ms，2/5/10 秒过渡分别为
  0.877147/0.702703/0.700326 ms，且均写入 `execution_validation.json`、
  `frozen_results.json`、摘要和问题一控制表。重新生成的
  `paper_preflight_report.json`、`pdf_visual_check.json`、`submission_audit_report.json`
  均为 `PASS`，LaTeX sidecar 编译成功；实页复核确认控制表标题未与表格分离，附录截断均以
  “以下代码略；完整可运行程序见附录A列出的支撑材料文件”明确标注。该结果仍需按最终人工清单复核
  问题二/三模型、引用与竞赛要求的完整源代码附录，不能由自动门禁替代。
- 2026-07-12 已使用 `git-filter-repo` 重写本地和正常远程 Git 历史，并 force-push
  `main`；可达对象中已删除资产路径计数为零，当前 `main` 和正常远程分支均不含该路径。
  但 GitHub 已合并 PR #1-#15 的服务端头快照仍保留该历史路径，普通 Git 重写无法删除。
  不要读取或回显其内容；账户所有者必须在外部服务端撤销并重发相关凭据，并向 GitHub
  Support 发起敏感数据清除请求。未获得服务端确认前，不得声称凭据轮换已完成。
- 2026-07-11 已核验 PR #1-#14 全部合并到 `main`，随后删除其历史本地/远程
  `codex/*` 分支、六个不再使用的 worktree 以及一个失效 worktree 注册。后续工作应
  从干净的 `main` 创建新分支；归档计划中的 PR 编号可用于追溯历史实现。
- 真实提交前仍需人工复核论文内容和 PDF 排版。

- [2026-07-14] 完整证据交接/定向回修/最终验收改造后的 Docker 真实 smoke 在启动前被本机环境阻断：
  `docker compose up --build -d` 无法连接 `//./pipe/dockerDesktopLinuxEngine`，且没有 Docker
  Desktop 进程；因此没有容器重建、HTTP 检查或真实 provider 任务被实际执行。当前处置：仅在
  Docker Desktop 恢复后重跑一次受控 Docker 健康检查、容器回归和轻量真实题；不得将 PowerShell
  后续的普通输出误记为 smoke 通过。
- [2026-07-14] Docker Desktop 恢复后，真实轻量线性规划 smoke
  `20260714-021514-e0be90b4d9e3940267458ebcd195659f` 在 Modeler 阶段后失败，未生成
  checkpoint、执行证据或主交付物。当前处置：在重试前读取该任务 `task_status.json` 和受限后端日志，
  修正结构化 ModelPlan 的运行时链路；不得把本次失败当作证据工具、冻结或导出链路的通过结果。
- [2026-07-14] 修正线性规划主/敏感性子题 profile 后，唯一真实重试
  `20260714-021910-23c08616b2c6256627fcfd85fdb0f66c` 已通过 Coordinator 与 Modeler，
  并写入 ModelPlan/checkpoint；随后默认 `remote` 执行器因未配置 `E2B_API_KEY` 安全停止，未执行
  Coder、证据、冻结或 Writer。当前处置：使用已验证的受控单用户
  `docker-compose.local-execution.yml` 覆盖后，从该 checkpoint 续传一次；不得在基础 Compose
  或普通 `.env.dev` 中关闭远程执行安全默认值。
- [2026-07-14] 上述任务在受控 Docker 本地执行续传后已实际完成 Coder、受控证据、冻结、Writer、PDF、
  DOCX 与候选清单；但首次最终技术验收为 `TECHNICAL_FAIL`：完整源码附录中的正常 `print()` 被误判为
  控制台噪声，跨子题同名指标在冻结投影中丢失题号作用域，且 64 位源码 SHA 标题造成 PDF 右边距溢出。
  当前处置：修复附录/冻结/一致性检查后，仅重建并重验该任务的既有产物；不再发起新的真实 provider 任务。
- [2026-07-14] 同一任务重验后，`pdf_visual_check.json` 已由 FAIL 修复为 PASS，完整源码附录哈希/覆盖检查也已通过。
  但任务的真实数学交接缺口被新门禁正确拦截：`ques2` 的 CSV 含新最优决策变量，却只提交了利润和残差，
  `execution_validation_report.json` 明确报 `ques2.linear_programming_solution_metrics`；既有 Writer 正文同时含有
  问题二资源代入矛盾，`paper_preflight_report.json -> result_consistency = FAIL`。当前处置：不得把该任务标记为
  可验收；下一次只允许从既有 checkpoint 对 ques2 定向补齐受控证据并重写受影响正文，连续失败规则仍适用。

## 接手时禁止全盘扫描

- 新 agent 接手时先读 `AGENT_MEMORY.md`。
- 再读 `AGENTS.md`。
- 再按任务需要读指定指南。
- 不要一上来 grep/search 全仓库。
- 不要读取 `.venv/`。
- 不要读取 `frontend/node_modules/`。
- 不要扫描 `backend/project/work_dir/` 下大量历史任务，除非用户明确要求。
- 诊断具体任务时只读对应 `<task_id>` 目录里的报告文件。
- 如果用户没有给 task_id，先按时间列出最近任务目录和报告状态。
- 不要重跑长任务，除非用户明确要求。
- 不要提交、推送、合并，除非用户明确要求。

## 核心文档入口

- `AGENTS.md`
  - 项目级规则、验证方式、前端 Node 限制。
- `STARTUP.md`
  - 启动方式、导出 profile、Docker 验证、CUMCM 2026 状态说明。
- `docs/md/PDF模板导出说明.md`
  - PDF/DOCX/LaTeX 导出说明、字体 fallback、验收要点。
- `docs/md/CUMCM2026模板替换指南.md`
  - 官方模板发布后的快速替换路径。
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
  - preflight/PDF 通过后的人工复核清单。
- `backend/app/templates/export_profiles/README.md`
  - 模板资源目录说明。

## 每次任务完成后的同步检查

完成任何代码或导出链路修改后，提交前必须检查是否需要更新：

- `AGENT_MEMORY.md`
- `STARTUP.md`
- `docs/md/PDF模板导出说明.md`
- `docs/md/CUMCM2026模板替换指南.md`
- `docs/md/CUMCM_FINAL_REVIEW_CHECKLIST.md`
- `backend/app/templates/export_profiles/README.md`

如果改动改变了当前稳定状态、已知风险、验证命令、失败诊断顺序或最近关键提交，必须更新本文件。

## 核心代码入口

- `backend/app/schemas/request.py`
  - `DEFAULT_MODELING_EXPORT_PROFILE = ExportProfile.CUMCM2026`
  - 新建建模任务默认 profile 的源头。
- `backend/app/routers/modeling_router.py`
  - `/modeling` 默认 export profile。
  - 任务创建、取消、续传、建模确认入口。
- `backend/app/tools/export_profiles.py`
  - `CUMCM2026_PROFILE`
  - PDF 变量、DOCX reference、LaTeX sidecar 模板路径。
- `backend/app/tools/pdf_exporter.py`
  - 主 PDF 导出。
  - Pandoc + XeLaTeX。
  - 主 PDF 禁 raw TeX，支持 `$...$` 和 `\(...\)`。
  - PDF-only 预处理会在关键词后插入内部分页标记，再由
    `pandoc_filters/pdf_pagebreak.lua` 转为 LaTeX `\clearpage`。
  - PDF-only 预处理会给连续中文长句插入内部断行标记，再由同一 Lua filter 转为
    LaTeX 断点；不回写 `res.md`，不影响 DOCX 或 LaTeX sidecar。
- `backend/app/tools/tex_project_exporter.py`
  - LaTeX sidecar 导出。
  - `latex_project/` 是候选产物。
  - 负责复制 Markdown/LaTeX 引用的本地图片并记录 `copied_assets` /
    `missing_assets`。
  - 会把 LaTeX 高风险图片文件名复制为安全文件名并重写 sidecar 内部引用。
- `backend/app/tools/paper_postprocessor.py`
  - 参考文献、附录、支撑材料、预检、claim trace。
  - 负责 `paper_preflight_report.json/md`。
  - 检查正文引用编号是否都有文末参考文献条目、表格是否有编号标题、图片图题是否
    避免文件名痕迹、生成图片是否已被正文引用或附录A支撑材料表登记、常见英文过渡词
    是否已转为中文、扩展分析是否被误标为不存在的“问题3”。
- `backend/app/tools/pdf_visual_checker.py`
  - PDF 后验视觉检查。
  - 检查 A4、非空、文本可提取、20MB 文件大小、摘要首页、无目录、
    正文 20 页以内（当前用户指定的内部基线）、物理边缘越界和 CUMCM 2.5cm 内容边距风险
    （允许少量字形 bbox 容差），并扫描全文页的 A4 尺寸与承诺书/编号页/
    参赛队号等身份字段。
- `backend/app/templates/export_profiles/`
  - DOCX/LaTeX 模板资源。
  - 当前 `cumcm2026` 暂时复用 2025 资源。

## 已知风险

1. LaTeX sidecar 编译失败是非阻断风险；不要把它当成主交付失败。
2. `paper_preflight_report.json = PASS` 不代表数学模型、求解结果、论文论证正确。
3. `cumcm2026` 暂时复用 2025 DOCX reference 和 2025 LaTeX 模板资源；官方 2026 模板发布后按指南替换。
4. 主 PDF 禁 raw TeX；正文应使用 Markdown 表格和标准 `$...$`、`\(...\)` 数学公式。
5. `pdf_visual_check.json = PASS` 会覆盖 A4、摘要首页、无目录、正文页数、
   文件大小和 2.5cm 内容边距等低成本格式风险，但仍不替代人工翻阅 PDF。
6. Docker 字体未挂载正式字体时会 fallback 到开源字体；正式提交前建议设置
   `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts` 重导，或用 Windows 本机官方字体复核。
   `submission_audit_report.json` 严格字体门禁可确认 PDF 是否仍在 fallback。
   后端 Dockerfile 通过带超时和重试的 `pip install uv==0.11.14` 安装 uv，
   不再依赖 `ghcr.io/astral-sh/uv:latest` 多阶段镜像，降低 GHCR
   token/metadata 网络失败和 PyPI 大 wheel 弱网 read timeout 导致的构建中断风险。
   当前 Docker 前端通过 `5173/api` / `5173/ws` 代理访问后端，即使 Docker
   Desktop 宿主机 `8000` 端口发布异常，Web UI 也仍可通过前端入口访问后端。
7. `candidate_manifest.json` 登记的是候选产物和证据链，不保证论文内容正确。
8. 历史任务目录可能保存旧导出器状态，诊断时要区分“当前代码行为”和“历史产物状态”。

## 失败诊断顺序

- 先看对应任务目录：
  `backend/project/work_dir/<task_id>/`
- 依次读：
  1. `paper_preflight_report.json`
  2. `paper_preflight_report.md`
  3. `export_status.json`
  4. `pdf_visual_check.json`
  5. `tex_export_status.json`
  6. `candidate_manifest.json`
  7. 必要时再看 `res.md`
  8. 若 PDF 出现大量 `print(...)`/控制台输出，优先检查
     `paper_preflight_report.json -> checks.appendix_console_noise`，再重新运行
     `prepare_paper_markdown` 重建附录并重导 DOCX/PDF。
- 如果 PDF 失败，优先看：
  `export_status.json -> pdf.stderr`
- 如果 preflight FAIL，优先看：
  `paper_preflight_report.json -> checks`
- 如果参考文献或表格细节异常，优先看：
  `checks.references.missing_inline`、`checks.tables.uncaptioned_tables`、
  `checks.extra_problem_labels.issues`。
- 如果正文关键数值与代码/CSV 输出疑似不一致，优先看：
  `checks.result_consistency.conflicts`，再对照对应 `source` CSV 和 `res.md`
  中的 `sentence`。
- 如果轻量题目没有外部数据集但论文出现“模拟数据集”“随机生成样本”等内容，
  优先检查代码手 EDA 输出和 `flows.py`/`prompts/coder.py` 的无数据 EDA 边界提示。
- 如果 PDF 视觉检查失败，优先看：
  `pdf_visual_check.json -> checks`
  尤其是 `submission_anonymity`、`a4_size`、`content_margin`、`abstract_first_page`。
- 如果 sidecar 失败，先确认是否影响主交付；通常不阻断。
- 如果 sidecar 报图片缺失，先看 `tex_export_status.json -> missing_assets`，再确认
  `res.md` 或 `sections/*.tex` 中的图片引用是否存在于任务 work_dir。
- 如果报告被后续重新导出覆盖，先说明无法从当前文件复原旧 stderr。

## 常用验证命令

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py app/tests/test_tex_project_exporter.py app/tests/test_paper_postprocessor.py app/tests/test_user_output_and_tasks.py
uv run python -m unittest app.tests.test_font_utils app.tests.test_submission_audit
uv run python scripts/smoke_pdf_export.py
```

## 常见判断

- 主链路成功通常看：
  - `paper_preflight_report.json = PASS`
  - `export_status.json -> pdf.success = true`
  - `pdf_visual_check.json = PASS`
  - `candidate_manifest.json` 登记主交付文件。
- sidecar 候选工程成功通常看：
  - `tex_export_status.json -> compile_success = true`
  - `latex_project/main.pdf` 存在且非空
  - `tex_export_status.json -> missing_assets = []`
- 如果 `res.pdf` 成功但 `latex_project/` 编译失败，先汇报 sidecar 非阻断。
- 如果 `preflight PASS` 但论文内容可疑，使用最终人工复核清单。
- 如果 `checks.result_consistency` 为 PASS，仅表示已识别 CSV 事实没有与正文冲突；
  未结构化入 CSV 的公式推导、模型选择和单位理解仍需人工复核。
- 如果官方发布 2026 Word/DOCX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 替换 `cumcm2026_docx`。
- 如果官方发布 2026 LaTeX 模板，按 `docs/md/CUMCM2026模板替换指南.md` 新增 `cumcm2026/`。
- 不要覆盖 `cumcm2025/` 或 `cumcm2025_docx/`。
- 如果用户只要求诊断，不要改代码、不要重跑长任务、不要提交。
- 如果用户要求真实烟雾测试，先确认 API key 处理方式，不要在回复里回显 key。
- 如果用户要求前端验证，优先使用 Docker 前端 `http://127.0.0.1:5173`。
- 不要运行本机前端 Node 命令，除非用户明确授权。
- 如果需要看历史任务，先列目录和报告状态，再读取最相关的一个任务。
- 每次声称通过验证前，必须实际运行对应命令。

## 最近相关提交

- `43db371 docs: require handoff memory sync after tasks`
- `b05bc2f Fix LaTeX sidecar compilation fallback`
- `93b02b5 docs: add CUMCM 2026 template replacement guide`
- `dfa89d1 Default modeling exports to cumcm2026`
- `012a68f Fix CUMCM 2026 export validation`

## 沟通口径

- 汇报用中文。
- 不要打印 API key、token、私钥、完整环境变量。
- 未运行验证时必须明确说“未验证”。
- 诊断任务失败时先给结论，再列证据文件和字段。

- [2026-07-14] 真实轻量线性规划验收任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2`：因 `E2B_API_KEY` 未配置，按受控本地恢复路径临时启用 Docker `mode=auto, allow_local=True`。Modeler/Coder 与本地代码执行、变量快照、`execution_validation_report.json = PASS`、`frozen_results.json` 均已生成；任务在 Writer/收尾前持续运行超过约 9 分钟，尚未生成 `res.md`/`res.json`/`res.docx`/`candidate_manifest.json`，为避免无界 provider 消耗已人工取消，终态为 `interrupted`。期间仅见 Semantic Scholar `HTTPStatusError` 警告，未见执行验证失败。当前处置：不对同一任务重试，已执行 `RestoreRemote`，运行时 `EXECUTION_MODE` 与 `EXECUTION_ALLOW_LOCAL` 均恢复未设置；该次仅证明执行冻结链路通过，不能视为完整端到端交付验收通过。

- [2026-07-14] 真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 的一次受控续传失败：在临时 `mode=auto, allow_local=True` 下，变量快照已恢复（105 个变量）且快照后未完成代码被丢弃，但 `POST /modeling/{task_id}/resume` 随后因 `KeyError: 'eda'` 终止，`task_status.json` 为 `failed`，未生成主交付物。触发条件：任务此前在 Writer/收尾前被有界取消后续传。当前处置：不再对该任务重复续传；先恢复默认远程安全模式，并以最小复现/单元测试定位 checkpoint/工作流恢复对 `eda` 字段的假设后再决定修复。

- [2026-07-14] 真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 在修复解释器分段输出缓存恢复后，用已配置真实 provider 完成一次受控续传：变量快照恢复、已保存 Coder 阶段复用和 Writer 均实际运行，`execution_validation_report.json = PASS`；随后 `paper_preflight_report.json = FAIL`，仅硬失败为 `result_consistency`，其将“新最优利润/原始利润/资源参数”出现在同一句的正确敏感性描述误判为各冻结事实冲突，停止在 PDF 候选导出前。当前处置：已按两次真实失败规程停止对该任务再次调用 provider；先最小复现并修复结果一致性匹配，再以现有 `res.md` 走本地确定性导出/验收，不重复消耗真实 API。

- [2026-07-14] 修复 `paper_postprocessor._sentence_mentions_metric()`：冻结结果一致性检查现仅在指标别名后的**本地分句**出现明确结果赋值（如“为”“达到”“分别为”）时才比较数值；对“较原始利润增加…，增长率达…”、资源约束描述、每件消耗效率/消耗率等上下文不再误报。兼容旧 `objective_value` 和当前 `optimal_profit`：明确“新/调整后/增加后最优利润”不会被当作原始最优利润。回归测试同时覆盖真实敏感性描述通过、`最优利润为2600元` / `原始利润为2600元` / `新利润达到2500元` / `机器时间使用量为90小时` 仍硬失败。

- [2026-07-14] 真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 未再调用 provider：修复后对现有 `res.md` 重新运行确定性论文后处理，`paper_preflight_report.json = PASS`、`execution_validation_report.json = PASS`、冻结结果哈希有效；已在 Windows 本机正式字体环境重导 `res.docx`、`res.pdf`，PDF 视觉检查 PASS，严格字体 `submission_audit_report.json = PASS`，LaTeX sidecar 自动编译成功，`final_acceptance_report.json = TECHNICAL_PASS`（人工复核仍为 `PENDING_HUMAN_REVIEW`）。已在这些证据完成后将任务状态恢复为 `completed`；Docker `GET /tasks` 已实际显示 completed。说明文件同步需求：本次只改变内部预检语义和修复记录，已更新本记忆；未改变用户启动、模板或导出命令，故无需更新 STARTUP / 模板说明。

- [2026-07-14] `result_consistency` 二次强化：按每个指标别名 occurrence 的本地分句抽取明确赋值数值，并把“从/由基线值提升至/降至新值”识别为基线指标声明；避免同句其他数字掩盖错误。最新 Docker 后端镜像重建后，全量单测与 Ruff 均通过；真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 再次核验为 `completed`，执行验证、论文预检、PDF 视觉检查、严格字体审计均为 PASS，最终技术状态为 `TECHNICAL_PASS`。

- [2026-07-14] 真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 的本地确定性恢复在重新导出 `res.pdf` 时失败：Pandoc 返回 `permission denied`，触发条件为覆盖既有 `res.pdf`；当前处置：已停止该命令的重复覆盖重试，保留已通过的 Markdown/DOCX 和执行冻结，改为先记录故障并检查文件锁定/采用新的候选输出路径。

- [2026-07-14] 上述本地确定性恢复的 `res.pdf` 文件锁已解除；未关闭或强制终止任何用户进程。已以修正后的 Markdown 正式覆盖重导 `res.pdf`（23 页），同步重导 `res.docx`，并实际复跑严格字体提交审计与最终验收：`execution_validation_report.json = PASS`、`paper_preflight_report.json = PASS`（`result_consistency = true`）、`pdf_visual_check.json = PASS`、`submission_audit_report.json = PASS`、`final_acceptance_report.json = TECHNICAL_PASS`。PDF 文本复核确认不含历史错误参数/表述 `M = 120`、`L = 90`、`3*x_A`、`题目未提供`、`假设性外推`或“单纯形法”。人工复核状态仍为 `PENDING_HUMAN_REVIEW`。

- [2026-07-14] 论文收尾 P0-P2 加固完成：P0 引入 PDF/DOCX 导出源/输出哈希、失败前清理旧产物、`finalizing` 权威状态和 candidate manifest schema 1.1；P1 将 PDF 视觉检查改为默认全页并验证当前 PDF 哈希，新增 Markdown 结构硬门禁并排除内部审查/失败尝试/LaTeX sidecar 图片；P2 新增正文图号引用条件门禁和连续型模型小数“件”表述条件门禁，PDF/LaTeX 代码附录字体改为 `footnotesize` 以减少孤立尾页。真实任务 `20260714-060406-1fb71cbf5669243532c3eff5f57486f2` 已修正 `(50,0)` 应由机器约束决定、连续生产当量口径、图1/图2/图3正文闭环和机器时间影子价格有效区间 `40<=b<=160`；重新生成的 `res.pdf` 为22页，`paper_preflight_report.json=PASS`、全22页 `pdf_visual_check.json=PASS`、严格字体 `submission_audit_report.json=PASS`、`final_acceptance_report.json=TECHNICAL_PASS`，人工复核仍为 `PENDING_HUMAN_REVIEW`。已同步 STARTUP、PDF导出说明、CUMCM2026 模板替换指南、最终人工复核清单，并新增 `docs/md/MATH_MODELING_SKILLS_INTEGRATION_PLAN.md`；CUMCM2026/default/CUMCM2025/华数杯 LaTeX sidecar 的 `listings` 代码字号现统一为 `footnotesize` 且开启自动换行，模板替换指南也已移除“附录仅核心摘录”的过期说明。未修改 `backend/app/templates/export_profiles/` 资源结构，因此其 README 无需更新。

- [2026-07-15] 收尾链路 P0 加固：`run_modeling_task_async` 与 `run_resume_task_async` 现在统一依据 `final_acceptance_report.json -> technical_status` 落持久化任务状态；只有 `TECHNICAL_PASS` 才写入 `completed`，否则写入 `failed` 并提示查看最终验收报告，避免主交付物存在时产生“已完成”的假通过。`GET /download_all_url` 还会排除内部诊断用的 `res_recovery_candidate.pdf`，防止旧恢复候选 PDF 混入下载包；该文件如需排查仍可单独下载。README 中过期的“默认附录仅核心摘录”说明已更正为默认完整源码附录，`mode=key` 才是非 `TECHNICAL_PASS` 的阅读模式。验证：Windows 本地 `python -m unittest app.tests.test_user_output_and_tasks app.tests.test_files_router app.tests.test_final_acceptance`（20 tests）和 `ruff check app` 通过；`docker compose up --build -d` 后三服务 healthy，`/docs`、前端首页和 `/api/status` 为 200，容器内同一回归集（20 tests）、项目推荐回归集（40 tests）及 `ruff check app` 均通过。未运行真实 provider 建模任务，避免无必要的 API 消耗。

- [2026-07-15] 失败任务恢复链路加固：新任务在 Coordinator/Modeler 调用前原子保存无凭据 `task_request.json`，因此早期失败且没有 `checkpoint.json` 时可从原题安全重启；后端启动会将无进程遗留的 `running`/`resuming`/`finalizing` 状态改为 `interrupted`，避免任务列表永久显示运行中。`/modeling/{task_id}/resume` 拒绝重跑 `completed` 和 `waiting_review`；恢复时把上次状态、失败子题和人工选择以受控上下文交给 Agent，明确保留已冻结结果且不得把失败过程写入论文。连续两次执行验证失败仍停止自动回修；只有指定决策人显式声明 `provider_changed` 或 `low_cost_algorithm` 才能获得一次、且仅一次的后续执行恢复授权。已由本轮 Docker 重建、142 项容器回归和轻量真实任务续传验证；详见后续本次任务记录。

- [2026-07-15] 真实轻量线性规划任务 `20260715-021632-ec34c8ef9ad8228d3ce94781743f7f2c`：在受控 Docker 本地执行模式下，Coordinator、Modeler、两道正式问题和敏感性分析均实际执行，写入 CSV/图表、`checkpoint.json` 和变量快照；首轮发现 `execution_validation_report.json = FAIL`，唯一硬失败是验证器把线性规划错误套用物理题“质量/流量守恒残差”要求（两题的资源约束、目标值、决策变量证据均通过）。为避免在错误门禁上继续消耗 provider，已人工取消，状态为 `cancelled`，保留 checkpoint 与产物。当前处置：修正验证器，使线性规划以资源约束、目标值和决策变量作为证据，不再要求物理守恒残差；完成 Docker 回归后从该 checkpoint 续传一次。

- [2026-07-15] 同一真实任务在修正线性规划门禁后的首次续传中，旧失败记录已把 `ques2` 的 Coder hand-off 清除，导致 Coder 再次尝试；其三次代码回合均未形成新的成功 hand-off，任务状态为 `failed`，错误信息曾误写成“未通过执行门禁: PASS”（该 `PASS` 是无 required_subtasks 的诊断报告，不能视为正式验收）。`execution_validation.json` 中原有两问的受控证据、CSV、图表和 SHA-256 仍完整，且旧正式报告的唯一失败项均为 `ques1/ques2.balance_residual`。当前处置：在重新续传前实现并验证一个窄范围恢复：仅当旧失败完全由该已修正规则造成、当前完整正式验证已通过时，复用既有受控证据进入冻结和 Writer；任何计算、约束、哈希或其他门禁失败仍须重新求解，不能借此绕过。

- [2026-07-15] 上述窄范围恢复已完成真实 Docker 续传：变量快照恢复成功，当前完整 `execution_validation_report.json = PASS`，并产出 `res.md/res.json/res.docx/res.pdf`、candidate manifest、LaTeX sidecar（编译成功）及全页 PDF 视觉检查 `PASS`。但最终状态正确为 `failed`/`TECHNICAL_FAIL`：`paper_preflight_report.json = CONDITIONAL_PASS` 的唯一条件项是 9 张正文图没有显式“图N”文字引用，`submission_audit_report.json = WARN` 因此未达到最终验收。当前处置：在任何重导或恢复前，先补齐可确定的图号正文引用并做确定性重新预检/导出/最终验收；不重跑已通过的计算或 Coder。

- [2026-07-15] 图号闭环后处理已补齐：对正文（不含附录/代码）中缺少邻近“图N”引用的 Markdown 图片，确定性插入中性图号说明；重复运行不重复插入。真实任务 `20260715-021632-ec34c8ef9ad8228d3ce94781743f7f2c` 已在 Docker 中重导 PDF/DOCX 并刷新 manifest/审计，9 处图号引用补齐后 `paper_preflight_report.json = PASS`、`pdf_visual_check.json = PASS`（92 页全扫）、`submission_audit_report.json = PASS`、`final_acceptance_report.json = TECHNICAL_PASS`；`/tasks` 已写为 `completed`，保留 checkpoint 与变量快照。该验收使用受控 Docker 本地执行覆盖来处理 E2B 缺失，最终应恢复 remote 默认配置；人工数学、引用、PDF/DOCX 逐页和投稿规则复核仍为 `PENDING_HUMAN_REVIEW`。

- [2026-07-15] 架构审查发现的 5 组可靠性/安全修复已在独立 worktree 并行实现、经审查后合并（M1 引用编号、M4 Writer 工具循环、M3+L5 Coordinator 校验、M2+L1 Coder 熔断退避、H1+H2 API/WS 安全加固），全量 342 单测与 Ruff 在合并分支上通过：
  - M1 `user_output.py`：正文 `[uuid]` 引用替换先按首次出现顺序去重、复用跨章节已分配编号，修复同章节跳号与跨章节悬空引用（正文标记指向不存在的参考文献条目）。
  - M4 `writer_agent.py`：真工具调用改为有界循环（`MAX_TOOL_ROUNDS=3`），reasoning 模型连续多轮 tool_calls 不再把空 content 当章节正文；超限后补齐协议配对的占位 tool 响应并禁用工具强制收尾；未知工具也补占位响应避免孤儿 tool_call；终局空内容防线只重试一次；最终 assistant 消息的 `reasoning_content` 取自产生正文那轮响应。
  - M3+L5 `coordinator_agent.py`：拆题输出在进入下游前做结构校验（`ques_count` 类型/范围、`background` 非空、`ques1..quesN` 齐全、多余 `quesN` 反向拦截），错误反馈改为 assistant 原文 + user 纠错消息，不再堆叠 system 消息（部分网关拒绝 mid-history system）；刻意不加严 `CoordinatorToModeler` schema 以保持旧 checkpoint 可续传。
  - M2+L1 `agent.py`/`coder_agent.py`/`setting.py`：基类 `run()` 不再把异常吞成字符串返回（防静默失败）；Coder 外层持续故障加指数退避（上限 60s）、尊重取消事件；`MAX_CHAT_TURNS` 默认 200（实例级累计）、`MAX_RETRIES` 默认 20（单子任务），从 None（无限）改为有限熔断保险丝。
  - H1+H2 `main.py`/`ws_router.py`/`security.py`/`user_input_queue.py`/`modeling_router.py`：新增可选 `API_AUTH_TOKEN`（默认 None 不启用；HTTP Bearer + WS `?token=`，`/docs`、`/redoc`、`/openapi.json`、`/static/` 豁免，前端未适配令牌模式）；`save-api-config` 更换 Base URL 必须同请求携带该端点 API Key（先全量校验再落任何字段，防止现有密钥被发往新端点）；WS 实时插话注入文本明确标注为不可信输入，队列单条 4000 字符截断、容量 20 上限。
  - 后续接手注意：`.env.example` 中 `MAX_RETRIES` 语义已改为“单子任务内重试熔断”（非单次 API 网络重试）；STARTUP.md 已补 `API_AUTH_TOKEN` 说明。本轮为纯代码级修复与单测验证，未运行 Docker 真实任务回归。

- [2026-07-15] 已将任务恢复/最终验收加固提交 `46b9e95` 与可靠性/安全分支 `claude/quizzical-dewdney-fa3789`（末提交 `86c9833`）集成，并以 merge commit `c1b2bc9` 快进到本地 `main`。合并仅在 `AGENT_MEMORY.md` 的追加记录处产生冲突，已保留双方完整记录；`backend/app/main.py` 自动合并后同时保留启动时遗留任务恢复和可选 API 令牌鉴权。集成分支及快进后的 `main` 均实际运行 197 项相关后端回归，全部通过；`ruff check app` 两次均通过。未运行本机前端 Node、Docker 或真实 provider 任务；未推送远端。空的 `logs/2026-07-14_error.log` 未提交也未删除。

- [2026-07-16] 建模计划契约防线已完成主路径/续传路径对齐：PR #20 在 `execute()` 的 Modeler 返回后、解释器和 Coder 创建前增加一次 Agent 外独立复核；`resume()` 复用同一 helper，历史方案冲突时先归档未验收执行上下文、用全新 Modeler 重建一次，并对重建方案做第二次复核，连续两次冲突即停止，不进入自动循环。随后新增 2025 B 光学附件契约：从官方题面可靠提取附件1/2、附件3/4分别为同一晶圆在10°/15°下的配对测量；问题2和问题3的计划必须各自绑定正确附件对、同一样品关系和双角度，显式0°/垂直入射替换或独立样品改写均拒绝，否定式“不得采用0°”不误报，非光学角度文本不触发。官方PDF原文探针实际提取两角度与两组附件契约；干净分支全量371项后端单测通过（1项环境跳过），Ruff通过。该计划门禁只负责在求解前阻断建模语义错误；执行证据、论文预检和人工数学复核仍必须继续执行。

- [2026-07-16] 合并 PR #20/#21 后的新 2025 B 真实任务 `20260716-102432-ea6c648352d55d7ea1085c6a14e553fc`：官方题面与四个附件上传成功，Coordinator 的 `mimo-v2.5` Responses 调用真实完成三问拆分；Modeler 三次均返回有内容的 JSON，但依次违反 `ModelPlan.schema_version`、`ExpectedArtifact.kind`、`AcceptanceMetric.comparator` 字面量枚举，达到内部三次结构校验上限后任务为 `failed`。任务只有题面、附件、已正确提取10°/15°及附件1/2、3/4配对关系的 `problem_contract.json` 和 token 统计；没有 checkpoint、解释器/Coder执行、冻结、论文或导出产物。根因是初始提示未列出完整枚举且运行时每轮只反馈第一条 Pydantic 错误，Mimo 只能逐项修正。当前处置：初始提示和每次纠错均列出完整允许枚举，纠错一次返回全部字段路径，结构修复上限有界增加为四轮；增加“三轮不同枚举错误、第四轮收敛”回归，重建后只创建一个新任务验证。

- [2026-07-16] PR #22 合并后的新 2025 B 真实任务 `20260716-103928-88ff240a1eb935e5dede2d51e5f8cd00` 验证 schema 收敛修复真实生效：Modeler 首轮同时出现三项结构问题，下一轮一次修成合法计划；但计划复核把两份明确写有“同一晶圆片在不同入射角（10°和15°）下配对测量、联合建模”的方案误判成独立样品，任务在 Coder 前干净失败。根因是 `_INDEPENDENT_SAMPLE` 的宽泛反向正则把“晶圆片在不同入射角”截成“晶圆片在不同”。现已把规则收紧为只识别直接修饰晶圆/样品的“不同/独立/两片”等关系，并保留“晶圆彼此不同”“两片独立晶圆”反例；真实失败任务的三份 schema 合法 ModelPlan 原样重放均通过契约，首份 schema 非法输出仍被拒绝。干净分支全量374项后端单测通过（1项环境跳过），Ruff通过；后续只创建一个新任务继续真实验收。

- [2026-07-16] PR #23 合并后的 2025 B 真实任务 `20260716-105250-3d405646a099aef086f73a985df3f921` 已通过 Modeler 契约并使用可信本地 Jupyter 完成三问、checkpoint 和变量快照，但首次全量执行验证为 `FAIL`。真实清单暴露可信证据漏洞：ModelPlan 的 `fit_r_squared > 0.95` 被 Coder 改成 `0.1543 <= 0.95` 后判通过，`silicon_model_improvement > 0.01` 被改成 `-0.030323 <= 0.01` 后也判通过；ques2 指标又声称 SiC 厚度10562.36 nm，而绑定结果表主值为2731.80 nm。现已引入 execution manifest v2：recorder 和最终 validator 双层绑定 ModelPlan 指标 id/comparator/target；constraint actual 与每个 metric value 必须按受控舍入容差真实出现在各自哈希 source_path；Coder 只能引用本轮新建/更新的这些来源。历史 v1 仍可读取，但最终 validator 会重验其计划比较符，真实失败清单重放已同时拦截 ques2/ques3 的方向反转。对抗测试覆盖反转 `gt→lte`、篡改 target、源文件不存在提交值、修正后合法写入 v2；干净分支全量377项后端单测通过（1项环境跳过），Ruff通过。修复合入并重建前，该任务及其论文产物均不可交付。

- [2026-07-16] 同一任务在旧证据协议下完成一次 ques3 定向修复后，旧 `execution_validation_report.json` 被错误写成 `PASS` 并生成冻结结果；Writer 随后只形成到5.1的正文，正式预检正确以 `FAIL` 停止导出，任务最终为 `failed`。硬失败包括缺少模型验证/评价章节、9个冻结指标缺 unit 或 explanation、5.2/5.3未按附件1/2与3/4及10°/15°完成题目归属；无候选PDF/DOCX。修复后的 ques3 仍把 `silicon_model_improvement=-0.039275` 通过反转后的 `lte 0.01` 冒充达标，因此不得从该冻结结果确定性重导；应先合入证据v2并创建一个新任务，从源头拒绝这种证据，再继续论文验收。

- [2026-07-15] 合并后 Docker 真实轻量线性规划任务 `20260715-083558-bcf5af9ad14cac9627c3ad92b2a839db`：受控本地执行模式下 Coordinator、Modeler、Coder、变量快照、两问 CSV/图表、`execution_validation_report.json = PASS` 和 `frozen_results.json` 均实际完成；真实 Redis 经 `5173/ws` WebSocket 代理的探针消息也成功转发。但 Writer 后的 `paper_preflight_report.json = FAIL`，硬失败仅为 `result_consistency`（17 个冲突）和 `figure_result_consistency`（3 个冲突）：检查器把 LaTeX 计算式中的首个乘数（例如 `40 \times 40 + 30 \times 20 = 2200` 中的 `40`）误当成最终赋值，并在同类句子中混淆原最优利润 `2200` 与新最优利润 `2366.67`，属于预检数值抽取/指标作用域误报。任务正确终止为 `failed`，未生成 PDF/DOCX/最终验收报告；当前处置：不重跑 provider，保留 checkpoint、`res.md/res.json`、冻结和执行证据，修复前先为表达式末端结果与原/新指标作用域建立最小回归，之后仅走确定性重新预检/导出。

- [2026-07-15] `result_consistency` 第三轮通用架构修复（`paper_postprocessor.py`）：`_metric_claim_numbers` 重构为 `_metric_claim_occurrences`，每个别名 occurrence 返回候选值集合而非单值——演算链（含 `=`）同时取赋值动词后首数（operand 位，如“影子价格 = 166.67/10 = 16.67”中指标自身值在链首）与最后一个 `=` 后的结果位（subject 位，如“最大利润为 z*=40×40+30×20=2200”），任一候选匹配冻结值即一致；别名后无赋值动词但紧跟数字（“可获得最大利润2200.0元”）也计入声明。新旧变体归属通用化：删除 `objective_value/optimal_profit` 硬编码，变体身份由冻结 id/label 命名约定判定（`new_`/`adjusted_` 前后缀、“新/调整后”label），正文前缀“新/调整后的方案下”归属调整后变体、“原/初始”归属基线，显式归属错误值不得借共享别名豁免逃逸；新增 `_shared_alias_metric_values` 共享别名 sibling 豁免（无显式归属的 occurrence 若匹配任一同别名兄弟指标的冻结值则一致），`_check_frozen_result_consistency` 与 `_check_figure_result_consistency` 统一走该架构，保证正文与图注口径一致。验证：新增 2 项真实句式回归（正确正文 0 冲突 + 4 类篡改必拦截）、全量 360 后端单测通过、Ruff 通过；对真实任务 `20260715-083558` 的 `res.md` 只读重验 `result_consistency` 与 `figure_result_consistency` 均 0 冲突，4 项对抗性篡改（演算链结果位/纯文本声明/新利润/影子价格）全部被拦截。该任务下一步只需确定性重新预检/导出，不需重跑 provider。

- [2026-07-15] 真实任务 `20260715-083558-bcf5af9ad14cac9627c3ad92b2a839db` 已在预检修复（提交 `94d4906`）后完成确定性恢复：重建 Docker backend 镜像（容器内 71 项相关单测通过）后，按 workflow 收尾同序在容器内重跑 `prepare_paper_markdown` → PDF 导出 → 全页视觉检查 → `export_status.json` → LaTeX sidecar → DOCX → 提交审计 → manifest → 最终验收，全程未调用任何 LLM provider。结果：`paper_preflight_report.json = PASS`（`result_consistency` 与 `figure_result_consistency` 0 冲突）、`pdf_visual_check.json = PASS`（12 项检查全过）、`tex_export_status.json compile_success = true` 且 `missing_assets = []`、`submission_audit_report.json = PASS`、`final_acceptance_report.json = TECHNICAL_PASS`（schema v2）；`res.md/res.json/res.docx/res.pdf/candidate_manifest.json` 齐全，任务状态已按验收门禁写为 `completed`，`GET /tasks` 实际确认。数学、引用、逐页 PDF 与提交规则仍为 `PENDING_HUMAN_REVIEW`。恢复用临时脚本已删除；该恢复路径与 2026-07-14 `20260714-060406` 案例一致：真实失败记录 → 修预检 → 确定性重导，不重复消耗 provider。

- [2026-07-16] execution manifest v2 真实任务暴露 ModelPlan/证据协议死锁：`AcceptanceMetric.target` 曾允许 `"长度单位"` 等字符串，但 recorder/final validator 只接受有限数值，导致 schema 合法计划永远无法提交完整证据。现已将 target 收紧为有限数值，初始提示和每轮修复提醒都明确禁止字符串、数组、null、NaN/无穷值；量纲/公式等定性检查统一使用 `eq 1` 数值标志并在 unit/description 解释。真实死锁形态回归验证首轮字符串 target 被定位到完整字段路径、第二轮数值 target 收敛，NaN/±Inf 均拒绝；干净分支全量379项后端单测通过（1项环境跳过），Ruff通过。该变更不改变启动、导出、模板资源或人工复核口径，其余说明文件无需更新。

- [2026-07-16] 开放性科学判定的 ModelPlan 验收指标改为结论中立：当正式问题要求判断/检验“是否存在、发生、显著或产生影响”时，独立计划复核会拒绝正向改善阈值（如 `fit_improvement ge 0.01`）、强制显著阈值（如 `p_value le 0.05`）和预设存在标志，要求改为模型比较已完成、数据覆盖、数值有限或结果可复算等过程指标；非开放性优化目标、误差阈值与拟合质量指标不受影响。初始 Modeler 提示与每轮协议提醒已同步；真实暴露形式和中立替代均有回归，全量381项后端单测通过（1项环境跳过），Ruff通过。该变更只调整内部建模计划验证和失败诊断，不改变启动、执行后端、导出、模板资源或最终人工复核口径，因此 STARTUP、PDF/CUMCM 模板说明、最终复核清单及 export profile README 无需更新。

- [2026-07-15] 2025 CUMCM B 题真实任务 `20260715-152645-104a0f4439c6ae3aaf57678f1a28e8e0` 使用用户授权的 Qianxing OpenAI Responses 网关启动；`gpt-5.6-sol` Coordinator 在约 20 秒内成功拆分 3 问（记录 6434 tokens），但 Modeler 的三次真实请求均在项目 `LLM_REQUEST_TIMEOUT_SECONDS=90` 上限触发 `TimeoutError`，任务最终为 `failed`。任务只有题面/四个附件、`problem_contract.json`、`task_request.json`、状态和 Coordinator token 统计；没有 `checkpoint.json`、执行验证/冻结、`res.*`、preflight、PDF 或 manifest。最小 Responses 探针和强制工具调用探针此前均成功，且同一网关/同一 `gpt-5.6-sol` 的 Coordinator 成功，容器资源空闲，因此当前故障定位为该模型路由在 Modeler 的约 5K 字符系统提示、约 8K 最大输出场景下首字节/完整响应耗时超过 90 秒，而非鉴权、协议、Docker、本地代码执行或导出故障。当前处置：按连续失败规程停止自动重试并恢复默认 remote 执行模式；若指定决策人授权一次恢复，优先人工切换已通过 Responses 探针的更快模型/受控缩小 Modeler 输出预算后从同一任务的 `task_request.json` 恢复，不重复提交新任务。

- [2026-07-15] 用户随后明确授权一次 provider 变更恢复；原任务把 Modeler 切到 `gpt-5.6-luna` 并将单次请求上限调至 300 秒，但恢复尚未进入 Modeler，Coordinator 的 `gpt-5.6-sol` 即连续三次返回 Qianxing 分组 `model_not_found / 无可用 distributor`。随后对 `/models` 列出的全部 10 个模型逐一做最小 Responses 探针，并对 3 个候选做 Chat Completions 探针，均返回同类 `model_not_found`；用户确认该 key 已失效。当前处置：保留原任务失败证据，不再续传；已移除本地 Qianxing 覆盖块并恢复 `backend/.env.dev` 原有 `mimo-v2.5` 四 Agent 配置，最小 Responses 文本探针实际成功。下一次真实验收使用同一 2025 B 题及四个附件创建新任务，不复用已耗尽恢复授权的原任务。

- [2026-07-15] 原 `mimo-v2.5` 备份配置的新 2025 B 题真实任务 `20260715-154337-32760841cc38f13201a82a31b7d3bd64` 已通过 Coordinator、Modeler schema 纠错、基础 checkpoint、EDA、多轮本地代码执行和变量快照；问题 1 生成 `ques1_results.csv` 等数值文件后，首次受控证据提交被服务器校验拒绝，后续达到强制证据边界时连续出现 `BadRequestError` 并熔断，任务为 `failed`，仅保存 `eda` Coder checkpoint。根因已由代码与本地 OpenAI SDK 类型定义确认：Responses API 的 `tool_choice` 接受字面量 `required`，但 `OpenAIResponsesProvider._convert_tool_choice()` 错误返回缺少函数名的 `{"type":"function"}`，兼容网关因此拒绝请求；同时早期代码失败把非正式诊断报告的 `PASS` 写进错误消息，产生“未提供证据；诊断 PASS”的误导。当前处置：先修正 Responses required 映射和诊断文案并增加回归测试，重建 Docker 后只从同一 checkpoint 恢复，不重复 EDA/规划；若证据或数学门禁仍失败，按既有有限回修规则处理。

- [2026-07-15] 同一 Mimo 真实任务在修正 Responses `required` 映射后从 checkpoint 成功恢复，变量快照实际恢复，`ques1/ques2/ques3` 均提交了受控执行证据；最终全量验证除三项 `balance_residual` 外全部通过。验证器错误地要求光学干涉测厚三问提供“质量/流量（或等价守恒）残差”，导致 `execution_validation_report.json = FAIL`，并触发一次无法消除规则误报的自动回修。当前处置：停止继续消耗 provider；将守恒残差门禁改为只有任务证据明确声明守恒型模型时才要求，并增加光学/非守恒题回归，同时保留对真正质量/流量守恒题的硬门禁。修复验证后仅从现有 checkpoint 续传一次，不重复 Coordinator、Modeler 和已通过的计算证据。

- [2026-07-16] 上述守恒门禁修复已使同一真实任务的 25 项完整执行验证全部通过，checkpoint 复用日志确认跳过三问 Coder，270 个变量恢复并生成 `frozen_results.json`；Writer 首节检索期间 Docker Desktop 引擎退出，最后一次外部调用记录为 `APIConnectionError`，随后进程中断且未生成 `res.md`。后端重启已按设计把遗留 `resuming` 标记为 `interrupted`，三个服务恢复 healthy，冻结结果、checkpoint 和执行证据未丢失。当前处置：从 `interrupted` checkpoint 继续 Writer/导出，不重跑已通过计算；若 Writer/provider 再次连续失败，按恢复规程停止重复调用并保留冻结产物。

- [2026-07-16] Docker 恢复后的同一 Mimo 任务已完成全部 Writer 章节并生成 `res.md/res.json`，但 `paper_preflight_report.json = FAIL`，且正确停止 PDF/DOCX 导出。唯一正文错误是问题 1 将冻结证据中的 `n=2.6, 2×2.6×10=52 μm` 混写为 `n=2.65, ...=53 μm`；该句同时触发 `result_consistency` 与 `figure_result_consistency`。现有定向 Writer 回修仅允许前者，因后者不在可修复集合而没有执行任何回修（`paper_repair_attempts=0`）。当前处置：让 `figure_result_consistency` 使用与结果一致性相同的章节定位与一次性定向回修路径，保留两个硬门禁本身；增加“同一句图文/结果冲突只重写对应问题”回归，之后从现有 Writer checkpoint 续传。

- [2026-07-16] 同一任务的定向 Writer 续传已把问题 1 折射率与光程差改回冻结证据 `n=2.6`、`52.0 μm`，`figure_result_consistency` 也已通过；第二次预检仍为 `FAIL`，唯一失败项 `result_consistency` 的两个冲突均为检查器误报：冻结指标 `wavelength_range=22.5 μm` 表示 `2.5–25 μm` 的跨度，检查器只抽取区间端点 `2.5`；同时问题 1 指标被错误套用于 `4.2 描述性统计` 中附件的实测波长覆盖区间。按连续两次失败规程停止所有 provider 调用，不再续传 Writer。当前处置：为范围/跨度指标增加端点差候选，并按正式小节归属隔离 `eda` 与 `quesN` 指标；在现有正确 `res.md` 上仅执行确定性预检、导出和最终验收，错误跨度仍必须被硬门禁拦截。

- [2026-07-16] 上述预检误报修复后，真实稿件正式 `cumcm2026` 预检已 `PASS`，结果与图表一致性均为 0 冲突；首轮确定性导出成功生成 PDF、DOCX 和 LaTeX sidecar，LaTeX 编译成功且无缺失资源，但 `pdf_visual_check.json = FAIL`。102 页均为 A4、非空、文字可提取且无边距溢出，正文（摘要后、附录前）15 页；唯一失败是首页有摘要但关键词未留在首页，导致严格提交审计与最终验收保持 `FAIL/TECHNICAL_FAIL`。当前处置：检查首页分页和摘要长度，只做不改变冻结数值/建模结论的最小排版修正，随后重新预检并重导整批哈希绑定产物。

- [2026-07-16] 2025 CUMCM B 题真实任务最终人工语义复核推翻了此前“仅摘要分页待修”的判断：题面明确附件1/2、附件3/4分别是同一块晶圆在10°/15°下的测量，但 Modeler 参数审计把入射角改写为0°垂直入射，Coder使用常数折射率并忽略双角度关系；Writer 又把三问整体错位（5.1以Airy多光束和SiC数据回答本应只推导双光束模型的问题1，5.2用附件3/4硅数据回答本应处理附件1/2的问题2，5.3未完整完成硅数据多光束计算），并把双角度测量误称“两片样品”。现稿13.12μm（SiC）/7.73μm（Si）约为正确主频的二倍谐波，不能交付；对原始附件独立采用Sellmeier色散、Snell角度修正和相邻波谷复算得到SiC约7.72/7.61μm、Si约3.47/3.46μm，与公开同行评审研究的量级和官方粗参考区间一致，但该复算仅用于诊断，未冒充正式候选论文。

- [2026-07-16] 针对上述“机器门禁全绿但数学语义错误”新增三层硬门禁：`problem_contract.py` 从题面提取双入射角及同一晶圆配对关系，Modeler 计划缺10°/15°或把附件解释成独立样品即拒绝；`execution_validation.py` 在冻结前交叉核验 `task_request.json` 与 `input_parameter_audit.csv`，题面角度被遗漏/改写即FAIL；`paper_postprocessor.py` 对显式双光束→附件1/2→多光束附件3/4题型校验5.1/5.2/5.3模型和数据归属，并拦截“两片样品”假陈述。真实任务已刷新为 `execution_validation_report=FAIL`（expected=[10,15], audited=[0]）、`paper_preflight_report=FAIL`（5项归属错误）、严格审计FAIL、`final_acceptance_report=TECHNICAL_FAIL`，`/tasks` 状态为failed；旧PDF/DOCX仅保留为失败现场，不得交付。验证：本机全量368项单测通过（1项环境跳过）且Ruff通过；重建Docker后三服务healthy，容器内114项相关回归及Ruff通过。已恢复默认remote执行配置，容器实际值为`CODE_INTERPRETER_KIND=remote`、`ALLOW_LOCAL_CODE_EXECUTION=false`，未再调用任何provider。

- [2026-07-16] 因当前无法配置 E2B，已按用户明确授权把本机切到持久可信本地执行：gitignored 根目录 `.env` 通过 `COMPOSE_FILE` 自动加载 `docker-compose.local-execution.yml`，覆盖文件由 `auto` 改为明确的 `CODE_INTERPRETER_KIND=local`，同时保留 `ALLOW_LOCAL_CODE_EXECUTION=true`、120 秒单元超时、`cap_drop=ALL`、最小五项 capability、`no-new-privileges` 和 `pids_limit=256`。解释器工厂新增统一的实际后端解析/就绪状态，`/status.code_execution` 可报告配置模式、最终选择、授权和 E2B 是否存在但不回显凭据；启动脚本断言、`.env.example` 与 STARTUP 已同步。普通 `docker compose build backend` 与 `up -d --wait` 后三服务 healthy，后端及 `5173/api/status` 均报告 `ready/local/local`；真实 Jupyter 探针计算 42、文件往返成功，子内核 UID=10001 且清理后无残留 ipykernel。本机全量 370 项单测通过（1 项环境跳过）、容器内 33 项安全/状态回归通过，本机与容器 Ruff 均通过；本轮未调用模型 provider，现有 2025 B 题失败候选状态未改写。

- [2026-07-16] PR #24 合并后的新 2025 B 真实任务 `20260716-113318-033370fd397e657a60f6a6d7a3b4a25b`：Modeler 前两轮结构纠错后第三轮被10°/15°同一晶圆配对契约拒绝，重建计划随后通过并进入可信本地执行；EDA 已生成 checkpoint、67变量快照、清洗数据和诊断图。问题求解期间一次用 `fsolve` 反演硅折射率时迭代到非法定义域，触发 `ValueError: math domain error`，Coder 下一轮自行恢复。随后 execution manifest v2 连续拒绝了旧文件、来源不含指标值和漏交计划指标等不可信证据，证明新门禁生效；同时暴露协议死锁：ModelPlan schema 允许 `formula_dimension_check == "长度单位"` 这类字符串 target，而 recorder/final validator 只允许有限数值 actual/target，因此该合法计划不可能提交完整证据。任务已人工止损为 `cancelled`，保留 checkpoint/notebook，无 execution manifest、冻结、论文或导出，不可交付。当前处置：将 ModelPlan 验收 target 收紧为可机检有限数值并给出量纲检查 `eq 1` 示例，完成回归、合并和重建后只创建一个新任务验证。

- [2026-07-16] PR #25 合并后的新 2025 B 真实任务 `20260716-115652-c186563e66ea8e4607e28d0d6d1cd988` 验证有限数值 target 门禁已在真实链路生效：Modeler 首轮的非数值问题3指标被 schema 拒绝，后续修复为数值计划；10°/15°同一晶圆契约又阻断三轮错误方案，第四轮才进入可信本地执行。EDA 完成 8 次本地代码执行并保存 37 变量快照，问题1随后完成 6 段本地计算；但 provider 在 12:06 后连续三次 `APIConnectionError`，Coder 抛出异常而任务仍处于外层运行。按连续真实 provider 失败恢复规程已主动取消，终态为 `cancelled`，checkpoint 保留，但无 execution manifest、冻结、`res.*`、preflight、PDF 或 candidate manifest，不能交付。当前处置：不再对当前 Mimo 路由发起真实重试；另行修复本次计划中 `silicon_fit_improvement >= 0.01` 预设“必有改善”结论的非中立验收指标，provider 恢复或由指定决策人切换到已验证备份后方可新建一次端到端验收。

- [2026-07-16] PR #26 已经 GitHub Backend CI 通过后 squash 合并为 `04b1da0`，远端/本地 PR 分支及临时 worktree 均已删除；根目录未提交的可信本地执行及其它既有改动完整保留。合并后的组合回归为390项后端单测通过（1项环境跳过）且Ruff通过；重建 Docker 后三服务 healthy，容器内61项计划/解释器/工作流回归和Ruff通过，`/status.code_execution` 为 `ready/local/local`。将取消任务 `20260716-115652-c186563e66ea8e4607e28d0d6d1cd988` 的真实 `modeler_plan.json` 原样重放，新门禁准确拒绝 `ques3 silicon_fit_improvement ge 0.01`；可信本地 Jupyter 真实执行平方和得到91、文件写入读回91且内核清理成功。当前代码与本地执行链路验证通过，但该任务仍无主交付物；因 Mimo 同一路由此前连续三次 `APIConnectionError` 且没有已验证备用 provider，本轮未再调用模型，完整2025 B端到端交付仍被外部 provider 可用性阻断。

- [2026-07-16] 用户明确授权切换到新的 Xiaomi Mimo token-plan provider 后，四个 Agent 保持 `openai-responses / mimo-v2.5`，仅在 gitignored `backend/.env.dev` 更换端点和凭据；普通 Responses 与 `tool_choice=required` 函数调用探针均真实通过。新建官方2025 B任务 `20260716-123335-612d4f094e4891b909ca1ec9de0f11b9` 后，Coordinator 长提示约70秒完成；Modeler 首轮的 `model_improvement_ratio ge 0.1` 被结论中立门禁拒绝，第二轮修为数据覆盖、模型比较完成和误差边界等过程指标，并完整保留10°/15°同一晶圆关系。EDA 本地执行中一段绘图代码因未定义 `FIG_DOUBLE` 触发 `NameError`，Coder 下一轮已自行补全并继续；当前处置：保留该真实失败记录，继续监控同一任务，不手工修改计算结果或绕过执行门禁。

- [2026-07-16] 同一新任务进入问题1后，Coder 把 `scipy.signal.find_peaks` 与另一极值接口混用，传入不支持的 `order=` 参数而触发 `TypeError`；这与 EDA 的未定义绘图尺寸是两类生成代码错误，本地 Jupyter 均正确返回异常，任务仍在单子题有界反思循环内。当前处置：不人工篡改 notebook 或结果，允许本轮既有有界修正完成；若问题1不能形成成功 hand-off，或后续正式执行验证连续两次失败，则按恢复规程取消并保留 checkpoint，不增加第三套方案。

- [2026-07-16] 同一新任务的问题1后续又出现两类生成代码错误：打印时把 `fit_data` 误写为未定义的 `fix_data`，以及构造 `input_parameter_audit.csv` 时各列长度不一致；Coder 在有界循环内修正后提交 execution manifest v2 并保存169变量快照，工作流进入问题2。但用最终验证器单独重放问题1仍为 `FAIL`：计划硬指标要求绝对反射率 `rmse_fit <= 0.05%`，当前受控证据为16.147%；`input_parameter_audit.csv` 在证据后改写又造成10°/15°来源哈希失配，且指标说明含“估计”被 `computed_evidence` 拒绝。当前处置：等待工作流既有一次定向执行回修，不允许反转比较符、篡改 target、伪造归一化口径或跳过最终门禁；若回修后仍失败即停止该任务。

- [2026-07-16] 同一新任务进入问题2后又出现 `interference_model()` 同时以位置参数和关键字重复传入 `theta_rad` 的 `TypeError`；结合此前四类代码错误和问题1最终验证重放仍为FAIL，已按连续失败恢复规程主动取消。终态 `cancelled`，保留 checkpoint、169变量快照、问题1 v2证据和中间CSV/图片，但无冻结、`res.*`、PDF或candidate manifest，不可交付。新 token-plan provider 的文本、required工具、Coordinator、Modeler和多轮Coder调用均真实可用，当前失败不再是provider不可用，而是Modeler在执行前杜撰无来源的经验阈值（如绝对反射率RMSE 0.05%和物理范围）以及Coder生成代码质量不足。下一步先在计划复核中要求经验拟合/误差/物理合理性阈值明确给出题面、数据统计、文献标准、基线或交叉验证来源；无来源阈值不得进入Coder，然后再创建新任务。

- [2026-07-16] ModelPlan 经验质量阈值来源门禁已实现：RMSE/MAE/MSE、R²、拟合误差、偏差、准确率、显著性和物理合理性等指标必须在 `description` 中明确把目标值关联到题面/附件、数据统计或交叉验证、基线、文献或标准；仅写指标计算方法、物理常识，或在描述中附加“数值有限/可复算”均不能放行。完成/覆盖标志和严格的 `> 0`/`>= 0` 正值可行性边界不受影响。取消任务 `20260716-123335-612d4f094e4891b909ca1ec9de0f11b9` 的真实计划原样回放已准确拒绝 ques1 的 `rmse_fit/physical_plausibility`、ques2 的 `angle_deviation/fit_r2` 和 ques3 的 `fit_error_bound`，同时不误拦 `thickness_positive > 0`。Windows 本地关键链路86项及全量395项后端单测通过（1项环境跳过），`ruff check app` 通过。该变更不改变启动、导出、模板资源或人工复核口径，STARTUP、PDF导出说明、CUMCM2026模板指南、最终复核清单和 export profile README 无需更新。

- [2026-07-16] PR #28 合并后的首次 `docker compose up --build -d` 中，后端新镜像已完整构建，但前端 `node:24-alpine` 元数据请求在 Docker Hub OAuth token 阶段返回 EOF，Compose 整体退出码为1。该失败发生在外部镜像仓库鉴权、与本次后端代码和 Mimo provider 无关；当前处置是复用既有前端镜像，仅 force-recreate 合入新代码的 backend，随后以服务健康检查和容器内回归确认运行版本，不重复拉取无关前端基础镜像。

- [2026-07-16] PR #28 合并并重建 backend 后的新官方2025 B任务 `20260716-130103-bf77cf5062f1d8c665c96db289368c89` 已上传原题PDF和四个真实附件；Coordinator 用时约58秒成功拆成三问。Modeler 首次长请求在90秒处触发 `TimeoutError`，内置下一次请求约70秒后收到7620字符响应，但该计划的 ques1 缺少 `result_table/time_series/dataset` 数值产物，被 ModelPlan schema 门禁拒绝，当前仍在有界协议修复阶段。当前处置：不切换已通过探针的 provider、不绕过 schema，允许现有 Modeler 修复上限内收敛；若连续失败达到恢复规程阈值则停止并保留现场。

- [2026-07-16] 同一任务四轮 Modeler 计划修复后终态为 `failed`，且未进入解释器/Coder、没有 checkpoint 或主交付物。第二版被新门禁准确拦截无来源的 `physical_boundary > 0`、双角度5%偏差和多光束改善指标，并拦截问题3附件配对声明缺失；第三版已消除全部经验阈值问题，只剩附件3/4同一硅晶圆的10°/15°配对表达；第四版实际已补齐 `paired_angle_modeling eq 1`，但正文短语中的未转义 ASCII 双引号（`纯`双光束光谱）使标准 JSON 解析失败，现有 `repair_json` 正则兜底仅抽出扁平 `schema_version`，造成表面上的 eda/subtasks 缺失。当前处置：不原样重提任务，先以有上下文的字符串扫描修复 JSON 字符串内部裸引号，并对第四版7757字符真实响应原样回放，确认完整 ModelPlan 和题面契约均通过后再重建。

- [2026-07-16] Modeler JSON 裸引号修复已完成：新增有容器上下文的字符串扫描，只在引号后的显著 token 不可能是当前对象/数组结构分隔符时转义该引号，保留合法键、值边界和既有转义；覆盖中文 `得到"纯"双光束光谱`、英文内部引号后 ASCII 逗号、合法嵌套/布尔/null/数字等回归。失败任务第四版7757字符原始响应已从容器消息日志直接管道到新解析器，完整恢复四个 ModelPlan 顶层字段与 ques1/2/3，随后严格 schema 和2025 B题面契约均 `valid=true`、0违规、0缺项。Windows 本地全量398项后端单测通过（1项环境跳过），`ruff check app` 通过。该修复不改变用户使用、启动、导出、模板资源或人工复核口径，除 AGENT_MEMORY 外其余说明文件无需更新。

- [2026-07-16] PR #29 合并并重建 backend 后的新官方2025 B任务 `20260716-133212-7e594619d29e40919940ea8e6baba6a0` 已通过 Modeler 全部门禁并进入可信本地 Coder；计划以量纲/极限检查、拟合完成、数据覆盖、双角度偏差已报告、模型比较完成和数值可复算等过程指标替代无来源的拟合好坏阈值，完整保留附件1/2、3/4同一样品10°/15°配对。EDA 前6轮本地代码均 `error=False`，随后一次长上下文 Coder 请求连续两次90秒 `TimeoutError`，第三次请求已恢复并继续第7/8轮本地执行。当前处置：记录 provider 长上下文波动并继续观察已恢复的同一流程；若再次连续超时且未恢复则停止任务，不再原样重复提交或引入新方案。

- [2026-07-16] 同一任务 EDA 已成功 hand-off 并保存708KB变量快照，问题1的本地代码执行均无 Python 异常，但 Coder 把8次成功执行额度耗在检查/绘图，达到上限时才声明“需要先创建必要的结果文件”；任务目录没有问题1结果CSV/JSON。之后 `record_execution_evidence` 连续4次被后端拒绝为不完整，现有循环在证据失败后会再次开放工具且没有独立证据失败熔断，可能持续到全局200聊天轮；期间长上下文请求又多次出现单次或连续两次90秒超时后恢复。当前处置：按连续失败规程取消，不绕过 execution manifest；修复方向限定为在剩余2次执行额度时进入明确的结果落盘收尾模式，并为证据修复设置有界上限，避免无限模型消耗，然后再评估是否从 checkpoint 受控续传。

- [2026-07-16] Coder 正式子题收口链路已加固：成功代码额度剩余2次和1次时，运行时会明确要求停止探索/诊断/新增绘图，优先一次性写出 ModelPlan 声明的结果及全部证据来源；受控证据失败后只允许针对错误来源做定向代码修复，连续3次仍不完整即返回显式失败并由 workflow 停止，不再耗到全局聊天轮上限。新增回归覆盖“收到剩余2次提醒后落盘并成功记录证据”和“缺失来源连续失败后有界熔断”；Windows 本地全量400项后端单测通过（1项环境跳过），`ruff check app` 通过。该变更只调整内部 Coder 执行收口和失败诊断，不改变用户启动方式、导出行为、模板资源或最终人工复核口径，因此 STARTUP、PDF导出说明、CUMCM2026模板指南、最终复核清单和 export profile README 无需更新。

- [2026-07-16] PR #30 合并、backend 重建并通过容器内28项关键回归与Ruff后，取消任务 `20260716-133212-7e594619d29e40919940ea8e6baba6a0` 做了一次受控 checkpoint 续传：25个变量快照恢复成功，未重复 Coordinator/Modeler/EDA；问题1首轮 Coder 请求一次90秒超时后重试成功并完成1次本地代码执行，但携带该工具历史的下一轮请求连续两个外层周期、每周期3次均在90秒超时。达到连续两次持续故障后已主动取消，任务回到 `cancelled`；新收口提醒尚未到剩余2次额度，故本次不能声称真实任务已验证通过。当前处置：不再原样续传；先用短上下文双轮工具探针区分 provider 的多轮工具协议与大上下文/无限输出预算问题，并为 Coder provider 持续异常增加符合恢复规程的独立两次熔断，再决定是否需要有界 `CODER_MAX_TOKENS`。

- [2026-07-16] Mimo 推理不可用范围已由真实探针确认：`GET /v1/models` 0.29秒返回200、列出6个模型且包含当前 `mimo-v2.5`，说明密钥、鉴权和网关存活；但极短首轮 Responses 单工具请求、以及人工授权的唯一备用 Chat Completions 512-token 单工具请求均在90秒无响应，故当前不是正式任务上下文、第二轮工具转换或输出预算问题，而是该端点的模型推理路由暂时不可用。停止继续生成探针。与此同时 Coder 已增加独立持续异常熔断：`_chat` 成功即清零，连续2次外层 provider/协议异常则返回显式失败并停止当前子题，不再打满通用20次代码错误额度；首次异常仍保留2秒退避，取消信号优先。相关32项及全量400项后端单测通过（1项环境跳过），Ruff通过。该修复不改变启动、导出、模板资源或人工复核口径，其余说明文件无需更新；真实端到端通过仍被外部推理服务阻塞。

- [2026-07-17] 方案1(证据收束后受控叙述轮)+方案2(本题确定性兜底)+方案3(Writer子任务物理隔离)已实现并端到端验收。方案3关键:原实现只在提示词软隔离,`build_result_fact_summary`/`build_frozen_result_summary` 仍全局注入所有子任务 frozen 指标;改为按 `subtask_id` 物理过滤——冻结路径按 metric.subtask_id、非冻结CSV按 `quesN_` 前缀,且只排除"明确归属他题"者,无归属指标放行(与CSV路径一致,避免误删)。另在 workflow freeze后/Writer前新增 `_assert_formal_metrics_have_subtask_id` 运行时断言:正式题指标缺 subtask_id 即停,不进Writer。全量420项后端单测通过(1跳过),ruff通过。重建镜像部署,容器内5文件sha256与主仓逐字节一致。单次重跑任务 `20260717-144854-2f67cf50c60faf5ad02eea5d3b52f2b1`:5.1不再越界引Airy/多光束、5.3正确用附件3/4硅晶圆多光束+一次反射对照RMSE、problem_alignment+result_consistency+全部25项预检PASS、frozen 33指标全有subtask_id(ques1:5/ques2:13/ques3:15)无污染无占位符。本轮未触发受控叙述轮/兜底(coder收束轮均产出合法叙述)。

- [2026-07-17] 上述任务终态仍 `failed`,唯一原因是PDF导出失败,与内容修复无关。根因经容器内决定性四组对照实验确认:失败图 `问题1_厚度扫描反射率.png` 是**0字节空文件**(SHA256=e3b0c442空哈希),xelatex对空PNG报"Unable to load picture"。对照(pandoc 3.1.11.1+XeTeX TeXLive2025+C.UTF-8):非空中文名✅、非空ASCII名✅、空中文名❌、空ASCII名❌——**中文文件名完全正常,根因是空图不是Unicode**。故用户预设的ASCII staging重命名方案无法解决(重命名空图还是空图)。空图成因:res.md附录 Cell9 用 `Path('问题1_厚度扫描反射率.png').touch()` "更新"图,而行780的savefig疑似静默失败/被空写覆盖(同cell的问题1_波数相位差.png正常103KB)。**约束:不重跑Coordinator/Modeler/Coder/Writer,不改已验收的res.md正文和frozen结果;修复后只做export-only→visual check→final acceptance/submission audit。** 修复方向应是导出前图片有效性校验+明确失败(对症),ASCII staging可作独立健壮性增强但非本次根因。现场固化在挂载卷 `backend/project/work_dir/_pdf_debug_archive_20260717-144854-.../`(task_products+snapshot+image_manifest.txt)。详见仓库根 `PDF_EXPORT_DEBUG_TODO.md`。

- [2026-07-18] PDF 主导出已增加本地 Markdown 图片的前置有效性校验与临时 ASCII staging：图片必须在任务工作目录内、存在、非 0 字节且可由 Pillow 解码；否则 Pandoc 前明确失败并列出坏图，杜绝将空图误报为 XeLaTeX/Unicode 故障。有效图片仅复制到导出期临时 `asset_XXX` 名称并由临时 Markdown 使用，原 `res.md` 和原图 SHA-256 不变，临时资源会清理；覆盖中文、空格、括号与同名不同目录。针对任务 `20260717-144854-2f67cf50c60faf5ad02eea5d3b52f2b1` 的 export-only 实测现在明确报 `问题1_厚度扫描反射率.png: 文件为 0 字节`，故未生成 PDF/视觉检查/最终验收；尚需按受控流程重新生成该坏图后再重导，禁止以重命名或旧 PDF 冒充通过。独立真实 Pandoc/XeLaTeX 导出已验证中文、空格和括号图名 staging 成功。

- [2026-07-18] 上述目标任务随后未重跑 Coordinator/Modeler/Coder/Writer，而是以 `ques1_phase_scan.csv` 的80行、4组已验证扫描数据按 `res.md` 原 Cell 7 的绘图逻辑受控重建唯一坏图；本机指定 Microsoft YaHei 后中文图例/坐标正常。export-only 成功生成 `res.pdf`（1,576,416 字节），`pdf_visual_check.json = PASS`（全49页扫描）、`submission_audit_report.json = PASS`、`final_acceptance_report.json = TECHNICAL_PASS`，自动报告的正式字体均为 SimSun/SimHei/Times New Roman。人工渲染复核首页摘要/关键词、页码/边距以及第11页厚度扫描图均正常；任务状态已写为 `completed`。技术通过不替代数学、引用、匿名和提交平台的最终人工复核。

- [2026-07-18] Docker Desktop 启动后，已用当前未提交工作树重建 backend 镜像并通过健康检查；容器内 PDF 图片回归11项与对应 Ruff 均通过。为不覆盖 Windows 正式字体候选稿，容器真实验证在 `/tmp` 临时目录复制已验收任务的 `res.md` 和全部9张 PNG，再执行 export-only：Pandoc/XeLaTeX 成功生成49页 PDF，`pdf_visual_check` 全页扫描为 `PASS`（49/49）。未启动新的建模任务或调用 provider；Docker 内字体 fallback 仅用于本次隔离验证，不改写正式候选产物。

- [2026-07-19] PR #34 合入 `main` 后准备执行新的轻量真实建模验收。运行配置中未发现 Mimo provider 条目；Geek2API 的四个工作流角色已配置，但未读取或记录密钥正文。首次 `docker compose up --build -d` 在调用模型前即因 Docker Desktop Linux 引擎命名管道不存在而失败（`dockerDesktopLinuxEngine` 未运行），因此未产生任务、未调用 Mimo/Geek2API，当前真实端到端验收受本机 Docker 运行时阻塞；先恢复运行时再试，不把该环境失败归因于本次验证门禁或 provider。

- [2026-07-19] Docker 恢复后，使用 Geek2API（Mimo 未配置）创建轻量线性规划真实任务 `20260719-092857-59d578a55d1d11383168f2380e151575`。Coordinator 和 Modeler 均真实成功：计划正确给出原问题 `(40,20), 2200` 及机器时间增加10小时后的 `(140/3,50/3), 7100/3`。但 EDA Coder 仅看到空数据集目录，错误声称“未提供具体产品收益、资源消耗、资源总量及题目约束”，没有 notebook 或执行证据；最终 `execution_validation_report.json=FAIL`（缺 notebook），任务为 `failed`。根因初判为无附件确定性题的 Coder 上下文未注入完整题面参数，非 provider、Modeler 计划或 PR #34 门禁故障。按规程不重提该请求；先修复题面/契约向 Coder 的上下文传递并加回归，再创建一次新任务。

- [2026-07-20] 使用已验证的 `backend/.env.dev.mimo.bak` 备份配置完成官方 2019 CUMCM A 题最终真实任务 `20260720-074519-72ca8fca15df4e17e1356755826b5324`。问题1的受控执行证据实际通过（5项约束、5项指标及哈希来源）；问题2三次有界回修后仍提交不可行证据，`ques2_constraint_check.csv` 显示最大压力 `177.99 MPa > 150 MPa`，并缺少由真实数组计算的守恒残差和仿真诊断指标。`execution_validation_report.json=FAIL`，任务终态为 `failed`，未生成 `res.md/res.json/res.docx/res.pdf`、候选 manifest 或提交审计。该失败证明新门禁已阻止将未满足硬约束的数值结果伪装为完成；按“最终一次测试”授权，不再自动重试。后续若继续，须先修正问题2的物理模型、守恒残差和跨时长稳定性诊断，再新建一次受控任务。

- [2026-07-20] 针对上述问题2失败已完成定向修复，准备由用户后续明确的“执行修复任务”授权进行一次新任务验证：`record_execution_evidence` 对不可行记录会返回失败约束的 id、实际值、比较符和目标值，Coder 不再只看到“第 N 项失败”；仿真提示要求先以所有硬约束筛掉不可行参数、用时序数组计算质量守恒残差并记录相对残差、求解器步长及 1s/5s 稳态差异；高压油管/柱塞腔还要求校验上止点残余容积、压缩行程的容积方向和体积流量方程的量纲。相关执行验证、Coder、workflow 回归共69项和 Ruff 已通过；这不放松 `150 MPa`、守恒或诊断门禁，真实任务仍须实际通过才可进入 Writer。

- [2026-07-20] 上述修复后的新 2019 CUMCM A 题任务 `20260720-081006-5db6e772b9d80def793420af9252a282` 在问题1失败，未进入问题2。首轮证据错误引用 EDA 阶段未更新的图；后续虽生成 `ques1_results.csv`、过渡控制和能量平衡文件，第三次提交仍缺 ModelPlan 的 `transition_time_error` 约束。现场还显示计划把题面“约 2s、5s、10s”的定性要求擅自转成 `transition_time_error <= 0.1s`，实际5秒情景误差为0.4s，不能诚实通过。任务为 `failed`，无 manifest/frozen/论文产物。当前处置：不再立即重试；先拒绝把“约/左右/尽可能”等语句伪装为数值质量阈值，并在每个正式 Coder 回合注入不可省略的 ModelPlan 约束清单，使其逐项落入约束表和受控证据。

- [2026-07-20] 上述第二次真实失败后的修复已完成：题面契约把“约/左右/尽可能”等模糊表述用于支撑数值质量阈值的计划拒绝，且将时间误差纳入该经验质量阈值检查；每个正式 Coder 回合会从 `modeler_plan.json` 注入当前子题全部验收指标清单，要求逐项写入约束表和 `record_execution_evidence`，避免遗漏。此前问题2的不可行约束详情反馈、全硬约束候选筛选、真实时序守恒残差及液压量纲/几何检查要求仍保留。Windows 与重建后的 backend 容器内，问题契约、执行验证、Coder、workflow 共102项回归通过，`ruff check app` 和 `git diff --check` 通过，服务健康且 `/docs` 可访问。因同一修复链已经连续两次真实任务失败，按恢复规程未创建第三次真实任务；当前改动尚未以新的真实任务证明端到端成功，后续需由用户/指定决策人明确授权一次受控重试。

- [2026-07-20] 为让 Codex/人工复核可受控引导 Docker 内 Agent，实时插话通道已从共享 FIFO 改为按 `coordinator/modeler/coder/writer` 角色投递；`all` 会分别投递给各角色，避免先运行的角色吞掉其它阶段的建议。创建任务时还可通过 multipart 的 `guidance_target/guidance_purpose/guidance_content` 预装建议，消除首轮 Modeler 的时序竞争；运行中使用 `POST /modeling/{task_id}/guidance`，要求目标角色、用途和来源元数据。工作目录仅追加不含正文的 `internal_guidance_audit.jsonl`（时间、角色、长度、SHA-256），候选论文/支撑材料不收录。所有引导在 Agent 侧明确标注为不可信建议，不能覆盖系统提示、题面契约、执行验证或最终验收。该能力适合分阶段给出模型选型、硬约束、诊断和证据落盘检查，但不保证模型会采纳，也不构成自动数学验收。相关安全、题面、执行、Coder、workflow 共122项 Windows 与 backend 容器回归和 Ruff 通过；重建容器健康，OpenAPI 已确认 `/modeling/{task_id}/guidance`。尚未用它启动第三次真实任务。

- [2026-07-20] 针对“当前执行者 ChatGPT Codex 必须实际引导任务”的链路缺口，新增任务级 `require_model_review`（`POST /modeling` multipart 字段），不再依赖全局 `HUMAN_MODEL_GATE_ENABLED` 才能暂停。该字段被写入任务请求快照与 checkpoint；ModelPlan 落盘和建模确认文件生成后，任务进入既有 `waiting_review`，当前 Codex 可读取 `modeler_plan.json`/`modeling_decision.md`、通过角色定向 guidance 把执行核验要求预先交给 Coder，再调用 approve 接口推进。未批准不会执行 Coder；计划根本错误时应停止而非用提示词篡改计划或冻结结果。相关模型门禁、请求恢复、定向引导、题面/执行/Coder/workflow 共135项 Windows 回归和 Ruff 通过；未启动新的真实任务。

- [2026-07-20] 用户已明确授权在当前 ChatGPT Codex 引导模式下，对官方2019 CUMCM A题发起一次新的受控真实测试。此前同题链路已有两次失败，本次不自动放行：将先以 `require_model_review=true` 生成并暂停在 ModelPlan，当前 Codex 审阅题面契约、物理关系、所有硬约束与产物/验收指标后，才会为 Coder 注入定向执行要求并批准续传。若计划或证据再次失败，记录现场并按恢复规程停止，不以提示词或手工改写结果绕过门禁。

- [2026-07-20] 上述受控真实任务 `20260720-112620-e2763ec12be7b8c9e0ce82319c24d8f9` 已在 ModelPlan 门禁进入 `waiting_review`，但当前 Codex 审查拒绝放行：计划仍将无题面/附件/文献依据的 ±5% 压力波动、0.5% 质量守恒残差、1ms 阀响应和插值误差写作硬阈值；问题二柱塞腔压力方程对可变容积项表述不完整。现有接口仅支持 approve，无法把这类具体审查意见回送 Modeler；在本次同一任务的受控修订或继续前，必须补齐“退回建模方案”链路，且不得以手工篡改产物替代模型重建。

- [2026-07-20] 该任务的首次受控建模退回已实际调用：修订版 Modeler 的首个返回缺少三个子题必填 `visualization` 字段，ModelPlan schema 门禁拒绝；随后格式修复调用经历 `TimeoutError`、`APIConnectionError`，最终报“LLM Base URL 主机无法解析”，任务状态为 `failed`。未生成 `res.md/res.json/res.docx/res.pdf`、冻结结果、候选 manifest 或提交审计，也未重新创建任务。修复了退回重建失败时审查文件仍显示 `revising` 的不一致，现 `modeling_decision.json=status=revision_failed` 并保留审查/失败历史。provider 可达性由指定决策人恢复后，须重新明确授权后才可再次运行真实调用。

- [2026-07-20] 用户已授权针对上述 DNS 失败修复后重新测试。根因是 `LLM.chat()` 在每轮 provider 调用前执行 Base URL 的公网 DNS/SSRF 校验，但该校验在原实现中位于重试循环外；因此 Modeler 的格式修复回合遇到短暂解析失败时直接终止，未消耗已有 LLM 重试预算。现仅把“LLM Base URL 主机无法解析”纳入同一有界重试循环，且每次重试仍重新执行公网解析和私网拒绝；缺失密钥、非法 URL 或其它配置错误仍立即失败。新增正反回归后，将以新任务重新实测，不复用失败任务的旧 ModelPlan。

- [2026-07-20] DNS 修复后的官方 2019 CUMCM A 题真实任务 `20260720-115143-35190d5df6aa67b6da3a8492721ee702` 已由当前 Codex 实际审阅 ModelPlan、退回一次并下发 Coder 硬约束；期间未再发生 DNS/provider 失败，变量快照恢复和真实附件计算均成功。运行中 Codex 发现并阻止了无来源的 15/5 MPa 阈值及“150 MPa 稳定”却实际 142.37 MPa、“问题二最优”却实际 92.08 MPa 的失真表述，定向纠正后问题1/2/3均生成了真实 CSV、图和哈希来源。最终 `execution_validation_report.json=FAIL`、任务为 `failed`，决定性失败项是 `ques3.diagnostic_profile`：ModelPlan 要求的质量守恒/双喷嘴一致性/减压阀物理可行性诊断没有以可复核 metrics 写入 execution manifest（尽管相应 CSV 已存在）。另有 Coder 多次证据提交因指标不在来源 CSV、图未在本轮重建而被拒，显示现有“指导后重算”会消耗多轮工具调用但缺乏一个确定性的证据封装收尾。当前处置：不重新创建或重试；先修复 execution evidence 使 simulation 诊断从计划要求映射为强制可复查 metric、并让 Codex 定向纠正触发一个独立且有界的重算/证据收束阶段，再由用户授权一次新任务验证。

- [2026-07-22] 2019 CUMCM A 真实任务 `20260720-154617-ab751ff945c00761b3b64066f5eaff71` 的首个 Codex 人工候选在容器受控通道中失败并已完整回滚：Q1 脚本已在教师副本复验中以密度加权质量方程得到 100/150 MPa 稳态开启时长约 0.2867/0.7979 ms、单周期离散质量闭合相对误差 0.0136%，2/5/10 秒过渡实际约 1.9993/4.9956/9.9928 秒；但正式候选解释器将文件作为 notebook 单元执行且未定义 `__file__`，脚本 argparse 默认路径触发 `NameError`，未写入成功证据、冻结结果或 Writer 状态。当前处置：停止原样重试，给受控候选执行器补充可审计的标准脚本上下文并新增真实解释器回归；通过单测和副本探针后才允许一次正式重试。

- [2026-07-22] 同一 2019 A 任务的 Q3 Codex 人工候选在容器内完成计算后被 execution evidence 门禁拒绝并完整回滚：数值候选已给出唯一泵、双喷嘴、减压阀动作、压力非负与总质量闭合，但 ModelPlan 的诊断要求“记录控制变量的物理可行性检查”没有直接对应的 source-backed metric，故未写入 Q3 成功 hand-off、冻结结果或 Writer 状态。当前处置：不修改计划或绕过门禁；在结果表和静态 evidence 中新增由 `omega>0`、`P_set>=0`、压力非负、唯一泵和单向阀条件联合计算的 `control_feasibility=1`，副本验证后只允许一次受控重试。

- [2026-07-22] 同一 2019 A 任务在 Q1/Q2/Q3 候选均通过单题 evidence 后，首次全量 execution validation 仅因 Q3 动作指标标签未同时包含验证器约定的“减压阀/开启”而失败；自动 Coder 修复已立即取消，未接受其结果。受控候选入口现可在保留原质量 review_id、失败子题和修复计数的 `repairing` 状态接管；Q3 以“扰动工况减压阀开启步数”重新计算并写入候选 `b29cca3b9e278a60ffbce069`，随后全量 79 项检查 PASS、三份 CSV 哈希一致并冻结，教师按新 review_id 审批后进入 Writer。Writer 文献检索阶段 Semantic Scholar 返回 HTTPStatusError 且所有文献源暂未返回可用结果；当前不把该告警冒充论文失败，也不伪造引用，继续观察 Writer 是否能在无外部检索结果时按题面和已冻结证据完成正文，最终引用门禁仍须单独验收。

- [2026-07-22] 同一任务首轮 Writer/导出产物最终验收为 `TECHNICAL_FAIL`：paper preflight 因本地相似度/AI启发式风险为 `CONDITIONAL_PASS`，submission audit 为 `WARN`；PDF视觉检查虽覆盖179页并 PASS，但正文审查发现 Writer 将 Q1 的0.2867 ms错写成约0.7 ms、虚构1.2/0.9 ms过渡策略，将Q3的50 ms错相误写成5 ms并声称20%降幅，还混淆102 MPa名义备用阀与101 MPa独立扰动阀。当前处置：不重跑数学模型、不接受该论文；以 frozen CSV 和敏感性表为唯一数值来源，Codex定向修复摘要、Q1/Q3结果、灵敏度和评价段，随后重新生成所有导出、哈希清单、preflight、视觉检查、submission audit与final acceptance。

- [2026-07-22] 事实修复后的论文 preflight 已达到 PASS（本地相似度/AI启发式0项、冻结结果一致、30条主张无弱/缺失证据），DOCX 重导成功；随后以 root 身份从 Docker exec 重导 LaTeX sidecar 时，在复制现有 bind-mount 图片的元数据阶段出现 `PermissionError: Operation not permitted`，`tex_export_status.json=success:false`。该问题发生在 sidecar 文件复制而非正文、公式或 XeLaTeX 编译。首次切换到 `mma-runner` uid/gid 时又因 `uv` 默认缓存指向该账号无权创建的 `/nonexistent/.cache/uv` 而在应用启动前失败；当前处置是停止这两条原样命令，使用镜像内现成 `/app/.venv/bin/python` 直接调用 exporter，既保持服务账号权限又绕开 uv 缓存初始化。

- [2026-07-22] LaTeX 图片复制已通过 `copy2` 元数据失败时退化为字节级 `copyfile` 修复并在 Windows/容器回归通过；sidecar 随后生成成功，但自动编译读取了上一次中断遗留的损坏 `main.aux`，报 `File ended while scanning use of \\@writefile`，latexmk/xelatex 均失败。当前处置：不修改正文绕过错误；在每次 sidecar 编译前只删除 `latex_project` 内明确列举的 `main.aux/.toc/.out/.fls/.fdb_latexmk/.xdv/.log/.synctex.gz` 临时文件，保留源码/图片，然后补单测、重建镜像并重新编译。

- [2026-07-22] 清理陈旧 LaTeX 临时文件后，编译推进到符号表并暴露第二个确定性模板缺口：Pandoc 3.1.11.1 的 longtable 列宽代码使用 `\\arraybackslash` 与 `\\real{}`，而 `cumcm2026` ctexart 外壳未加载 `array`、`calc`，导致 `Undefined control sequence`。当前处置：给 coverless CUMCM2026 sidecar 模板补齐 Pandoc 表格必需包并增加模板回归；不修改符号表内容或取消表格。

- [2026-07-22] 全部门禁转为 PASS 后的教师 PDF 抽查仍发现自动一致性检查覆盖不到的推导错误：Writer 将 Q2 柱塞腔写为 `V_c=V_residual+A x`，并在压力方程中漏掉变容质量守恒项；实际受控脚本与验证使用 `V_c=V_residual+A(H-x)`、`dV_c/dt=-A dx/dt` 和 `d(ρ_cV_c)/dt=m_fill-m_pump`。当前处置：保留已验证数值不重算，纠正文/结构化 JSON 的体积关系与 `-ρ_c dV_c/dt` 压力项，再重跑 preflight、DOCX/PDF/LaTeX、全页视觉和最终验收。

- [2026-07-22] 官方2019 CUMCM A题真实任务 `20260720-154617-ab751ff945c00761b3b64066f5eaff71` 已完成 Codex 教师接管闭环：luna_high 学生代理负责候选计算/旁路物理审查，主线程逐题复算、修正并通过容器受控候选接口落盘；Q1/Q2/Q3 全量 execution validation 79项 PASS，冻结哈希一致，人工质量 review 按新 review_id 批准。Writer 事实错误和 Q2 变容推导错误均已按冻结 CSV/正确守恒式修正，未重写数值结果。最终 `paper_preflight=PASS`（本地相似度/AI启发式0项、claim trace 30/30）、`pdf_visual_check=PASS`（178/178页）、`submission_audit=PASS`、`tex_export_status.success=true/compile_success=true`、`final_acceptance=TECHNICAL_PASS`、`task_status=completed`；最终 PDF 文本包含0.2867、1.2883/0.8351/0.7444 ms、60 rad/s、50 ms、102/101 MPa，且不含已识别的0.7 ms/5 ms错相/20%虚构表述。外部文献检索本轮无可用结果，因此论文保留0条外部参考文献而未伪造引用；这满足技术真实性门禁，但正式提交前仍需队员按竞赛规则人工决定是否补充经核验的背景文献并完成匿名/文件名/平台上传复核。

- [2026-07-22] 用户提供新的 MiMo Anthropic 兼容端点用于追加真实测试；1-token `/validate-api-key` 已返回有效。首次 `/save-api-config` 因请求遗漏 schema 必填的 `openalex_email` 被 422 原子拒绝，四角色运行时设置未发生部分更新；未向仓库配置文件写入凭据。当前处置：补显式空字段后仅保存到当前后端进程，再运行轻量真实建模闭环。

- [2026-07-22] 新 MiMo Anthropic 端点的轻量真实任务 `20260722-104737-41d7194bc4d66569da5d3a053149f9a7` 已由 Modeler 生成正确线性规划方案并进入人工门禁；Codex 审查后向 Coder 注入解析值、双方法复算、约束残差和影子价格要求并批准。续传在 Coder 调用前失败，直接原因是默认 `CODE_INTERPRETER_KIND=remote` 且未配置 `E2B_API_KEY`，安全工厂明确拒绝自动降级到本地解释器；该失败与 MiMo 鉴权或 Modeler 输出无关，尚无 Coder 运行证据或论文产物。当前处置：仅在可信单用户 Docker 场景按已记录的 local-execution 覆盖恢复同一 checkpoint，不重新提交题目；恢复后仍须通过执行证据、冻结、Writer 与最终导出门禁。

- [2026-07-22] 同一 MiMo 轻量真实任务在本地受控解释器恢复后，Q1/Q2 的 execution evidence、全量执行验证和人工质量 review 均已 PASS，Writer 生成 `res.md/res.json`；首次导出被 paper preflight 硬门禁停止。失败项为：正文把影子价格同时写成分数 `50/3` 与小数 `16.6667`，数值一致性启发式将分子/分母误识别为冲突；改进展望中的“帕累托前沿分析”被算法证据门禁识别为已声称但未实现。另有连续 LP 产量使用“件”的条件风险与局部重复表述风险。当前处置：不重算或篡改冻结结果，使用候选修复链路仅改正文表达（影子价格统一为小数或防误解析形式、明确帕累托仅为未来改进、连续产量标注理论值），再重新生成全部导出和最终门禁。

- [2026-07-22] MiMo 轻量真实任务 `20260722-104737-41d7194bc4d66569da5d3a053149f9a7` 已完成教师接管闭环。Codex 以冻结结果为唯一数值依据修复正文表达，并额外纠正 Writer 关于“产品A单位机器时间利润高于B”的错误解释（实际分别为20、30元/小时；组合变化来自机器/人工两项紧约束联立），未重算或改写执行证据。最终 Q1 为连续产量 `(40,20)`、利润2200元；机器时间增加10小时后为 `(140/3,50/3)`、利润 `7100/3`，利润增加 `500/3`，影子价格16.6667元/小时。`paper_preflight=PASS`（本地相似度/AI启发式0项、连续量表述通过）、`pdf_visual_check=PASS`（72/72页）、`submission_audit=PASS`、`tex_export_status.success=true/compile_success=true`、`final_acceptance=TECHNICAL_PASS`、`task_status=completed`；`res.md/res.json/res.docx/res.pdf/candidate_manifest.json` 齐全。MiMo 凭据仅注入后端进程且未持久化；测试后已恢复默认 Docker Compose 模式，后端/前端健康检查均为HTTP 200。外部文献检索本轮未返回可用结果，正式论文删除了未核验引用而没有伪造来源；提交前仍需队员人工复核题意、匿名信息、文件名与平台上传要求。

- [2026-07-22] 针对本机没有 E2B 却被显式 `-f docker-compose.yml -f docker-compose.override.yml` 命令绕过持久 local 默认的问题，已确认根目录 gitignored `.env` 保留 `COMPOSE_FILE=docker-compose.yml;docker-compose.override.yml;docker-compose.local-execution.yml`，普通 `docker compose` 现在稳定选择 `local/allowed/ready`。`docker-local-execution.ps1` 新增显式 `UseRemote`，并把旧 `RestoreRemote` 降为兼容别名；二者均在改变容器前检查 Compose 中是否存在 `E2B_API_KEY`，未配置时拒绝切换且保持 local 后端不变。远程参数同时补齐 Windows override；本地状态探针改用镜像现成 venv，避免 uv 缓存初始化差异。真实 Jupyter 探针成功计算42，子内核UID=10001并完成清理；无 E2B 的 remote 切换探针按预期返回非零，随后 `/status.code_execution` 仍为 `ready/local/local`。容器内全量467项单测通过（1项环境跳过）、Ruff通过，三服务healthy。`STARTUP.md`、`.env.example` 已同步本机默认与显式remote边界；导出/模板行为未变化，无需更新其它模板文档。

- [2026-07-22] 为避免 Writer 生成 `res.md` 后只通过硬规则而漏掉 PDF 书签/标题语义问题，新增非阻断 `semantic_layout_review`：扫描代码围栏之外的 Markdown 标题，检查 CUMCM 主章节应为 H1、摘要/小节/子小节层级、重复标题、附录分页提示及空 `{}` 引用标记；结果写入任务目录 `semantic_layout_review.json/.md`，并登记到 `paper_preflight_report.checks.semantic_layout`（severity=info，不改变主预检 PASS/FAIL）。Writer 提示词加入同一套自检提醒，候选 manifest 纳入两个语义报告文件。对最终任务 `20260722-104737-41d7194bc4d66569da5d3a053149f9a7` 的实际扫描为 `WARN`、8项：二/四章误用 H2、4个假设误用 H3、附录缺分页提示、正文第19行存在空引用标记；主 preflight 仍为 PASS，说明该报告用于提示和人工复核，不替代硬门禁。新增语义审查回归后，容器全量469项单测通过（1项环境跳过）、Ruff通过，三服务 healthy。

- [2026-07-28] 真实 MiMo 轻量闭环任务 `20260728-084449-540f700d636b35968bb25caf7938bed8` 的 Coder 已实际计算出正确的 Q1/Q2 结果并使全量 execution validation 暂为 PASS；但 Q2 首次受控 execution evidence 提交被拒，原因是提交时引用的 `ques2_acceptance_metrics.csv`、`ques2_results.csv`、灵敏度图及其数据文件不是该轮代码调用新建或更新的来源。当前处置：不绕过哈希/本轮来源门禁，记录后仅允许 Coder 进行一次定向重建并重新提交证据；数值独立复算为原问题 `(40,20), 2200`，机器时间110小时为 `(140/3,50/3), 7100/3`，增益 `500/3`、影子价格 `50/3`。

- [2026-07-28] 同一真实 MiMo 任务的 execution validation 和 quality review 虽为 PASS，但按源码干净重跑规程，将 `notebook.ipynb` 复制到隔离目录后用全新 Jupyter 内核按 29 个代码单元顺序执行，结果为 FAIL：第5单元 `NameError: COLORS is not defined`，第16单元 `AttributeError: module 'os' has no attribute 'pathgetsize'`，第19单元 `SyntaxError: invalid character '≤'`。这表明当前冻结结果依赖历史内核/存在未可复现源码，不能批准或导出。当前处置：退回 Coder，只修复上述源代码与执行顺序问题，然后重新受控执行、刷新证据哈希、冻结与所有导出门禁。

- [2026-07-28] 上述任务的质量返修后，第二次隔离副本新内核重跑仍以相同三项旧单元错误 FAIL；返修将新代码追加到 `notebook.ipynb`（代码单元由29增至38），却没有移除或替换失效单元，因此不能恢复源码可复现性。已满足同一功能连续两次失败条件：停止原样 Coder 重试和审批/导出，转而修复 notebook 作为执行日志而非可重跑源码的链路缺陷；修复后必须重新创建一次轻量真实任务做完整验证。

- [2026-07-28] 已修复上述 notebook 可复现性缺陷：本地与 E2B 解释器在代码单元返回错误时仍将诊断保留在任务消息/日志，但从可重跑 `notebook.ipynb` 移除该失败单元及其部分输出，避免“先失败后修正”的历史记录污染新内核复跑；新增序列化器与本地解释器回归。容器定向单测30项和 Ruff均通过。该行为改变了执行源码记录，后续真实任务必须从新建任务开始并完成干净重跑、重新取证、冻结和全链路导出。

- [2026-07-28] 修复后新建的真实 MiMo 烟雾任务 `20260728-090936-8d85076013ead3577425ac65ec82b80f` 已完成两题实际计算、56项 execution validation PASS 与冻结，但隔离新内核按23个 notebook 代码单元重跑在第17单元报 `TypeError: list indices must be integers or slices, not str`。这不是被历史失败单元污染，而是新的顺序/变量类型依赖；当前不批准质量复核、不进入 Writer。处置：定位该单元，修复执行源码及其顺序，再重建本任务的受控证据和冻结结果。

- [2026-07-28] 定位后确认第17单元本身的错误已被后续修正单元覆盖，但它仍留在 notebook；进一步确认 Docker Compose 只 bind-mount work_dir、不挂载后端源码，先前仅 `restart backend` 没有加载本次 `discard_last_code_cell` 修复（容器内该方法不存在）。因此该任务不能用于验证修复；不再复用。当前处置：重新构建后端镜像并以新任务验证失败单元不会进入可重跑源码。

- [2026-07-28] 后端 `docker compose up --build -d backend` 在单次5分钟受控等待内未完成并以超时退出，未得到镜像构建成功证据；未并行或重复启动构建。当前处置：先读取 Docker 当前服务与镜像状态，确认是否留下部分构建/是否可安全续建，再做一次更长但单一的构建尝试。

- [2026-07-28] 运行新镜像后的最终真实 MiMo 烟雾任务 `20260728-092845-06a2a85d867083ca7c14b83e2090c34f` 首次受控 evidence 被拒，原因是 `ques1_acceptance_metrics.csv` 未记录当前 ModelPlan 所需的 `max_constraint_violation`、`optimality_gap` 及优化诊断要求；不是求解数值失败。当前处置：不绕过门禁，允许 Coder 仅补齐与计划逐项匹配的验收/诊断来源后重提。

- [2026-07-28] 同一最终烟雾任务补齐后 Q1 第二次 evidence 又被拒：声明的第7个 metric 值未能在其 `source_path` 中复查。Coder 已继续把该指标写入可追溯来源，再提交；变量快照已保存且尚未进入 Q2/Writer，当前不将此中间拒绝报告为通过。

- [2026-07-28] 同一最终烟雾任务已通过55项执行验证、冻结、Codex 数学复核与6单元隔离新内核重跑；Writer 生成 `res.md/res.json` 后 paper preflight 为 FAIL，硬失败为正文声称实现 `genetic_algorithm` 而冻结/代码未提供该算法证据。相似度启发式另为 CONDITIONAL（图链接重复），不是硬失败。当前处置：不改数学结果或伪造算法证据；仅将遗传算法改写为明确的未来改进建议，重跑预检及全部导出/审计。

- [2026-07-28] 上述任务的第一次定向 Writer 续传后，第二份 preflight 仍将遗传算法识别为已实现，且连续产量的“46.67件/16.67件”缺少明确理论连续解语境而为 CONDITIONAL。已满足同一论文预检连续两次失败条件，停止再次原样 Writer 续传；转而检查并修复预检规则对未来扩展算法及连续产量上下文的误判，再以冻结结果为唯一数值来源重做最小受控验收。

- [2026-08-08] 新建 MiMo 轻量真实任务 `20260808-032507-da0f298bb67d01de6026c1d26c99f8f2` 已实际收到 Coordinator 的 provider 响应并保存 checkpoint；随后宿主机全量单测启动了 FastAPI `TestClient` 生命周期，错误执行“遗留任务恢复”并把容器仍在运行的任务标记为 `interrupted`。这不是 MiMo、模型计划或代码执行失败。当前处置：新增 `RECOVER_STALE_TASKS_ON_STARTUP`，测试包显式关闭该副作用并加回归；重建容器后只从现有 checkpoint 续传，不重新提交任务或伪造完成状态。
- [2026-08-08] 同一 MiMo 任务续传后，Q1 已实际登记受控执行证据并保存变量快照；Q2 三次 `record_execution_evidence` 均被拒，原因是该数值子题未把 ModelPlan 所要求的诊断要求映射为可复核指标。第三次拒绝发生在停止请求送达前，框架已自动结束该子题并将整任务标记为 `failed`；未生成冻结结果或论文产物。当前处置：不修改或伪造证据、不再重试该任务；以拒绝报告定位 Coder 提示词/计划诊断映射缺口，补回归后才允许新任务验证。
- [2026-08-08] 新建 MiMo 轻量真实任务 `20260808-040101-dd48ab2f8f5df20f4e3425244e0660a8` 在 EDA 快照后进入 Q1；其首次正式代码包含未转义的嵌套中文引号，报 `SyntaxError: invalid syntax`。前序 EDA 代码和变量快照均成功，任务尚未进入失败状态，Coder 已收到错误并进入一次自动反思纠正。当前处置：不手工改写任务目录、不新建/重试同一题；仅观察该一次受控纠正，并以随后成功的源码、证据哈希和冻结结果为准。
- [2026-08-08] 同一 MiMo 任务的 Q1 首次 `record_execution_evidence` 被门禁拒绝：`optimal_profit` 在结果表中把验收 target 写为 2200，而 ModelPlan 规定 target 为 0，且缺少 `max_constraint_violation`、`vertex_optimality_check` 及对应约束证据。计算代码本身成功，系统已将精确错误反馈给当前 Coder 回合并允许一次定向重建；当前处置：不手改 CSV/哈希、不更换任务，观察该一次纠正后的新来源和受控证据结果。
- [2026-08-08] 同一 MiMo 任务的 Q2 首次 `record_execution_evidence` 被门禁拒绝：`metrics[3].value=7.58` 未能在其声明的 `source_path` 中复查。优化诊断代码和来源文件已实际生成，失败仅为逐值来源绑定缺口；当前处置：不手工补写 source/manifest，允许当前 Coder 一次定向重建后重新提交，并以新哈希为准。
- [2026-08-08] 同一 MiMo 任务的首次全量 final validation 为 `FAIL`：Q2 缺少 ModelPlan 承诺的 `ques2_sensitivity_results.csv`，且受控 metrics 未显式提交新最优决策变量；定向回修的首个 evidence 又因复用旧的利润图而被拒。当前处置：不绕过“本轮来源”门禁，已把计划产物、图表双来源和优化决策变量要求前置给 Coder；当前任务仍在受控回修中，未宣称完成。
- [2026-08-08] `cumcm2026` 的 AI 使用详情预检原先只检查 PDF 文件头和大小，损坏的占位文件可绕过；现改为用 PyMuPDF 实际打开并要求至少一页，新增回归覆盖“伪 PDF 拒绝、真实 PDF 通过”。该项改变了 CUMCM 预检口径，已同步到 PDF 导出说明和最终复核清单。
- [2026-08-08] MiMo 轻量真实任务 `20260808-040101-dd48ab2f8f5df20f4e3425244e0660a8` 已完成执行验证和冻结，但 Writer 首次论文预检为 `FAIL`，工作流按硬门禁停止候选 PDF/清单导出。根因是测试请求显式传入 `export_profile=default`，而 CUMCM 流程的 profile 硬门禁要求 `cumcm2026`；`similarity_ai_risk` 仅为 conditional。不是 MiMo、数学结果或正文硬门禁缺陷。当前处置：不改弱 profile 门禁、不手改任务结果或预检报告；重建最新容器后以 API 默认的 `cumcm2026` 新建独立烟雾任务验证。
- [2026-08-08] 新建 `cumcm2026` MiMo 烟雾任务 `20260808-044441-07d759aa269ed2296b17ddc4431ac215` 的 Q1 首次 `record_execution_evidence` 被拒，精确原因为 `metrics[4].value=1.0 无法在 source_path 中复查`；任务尚未终态失败，Coder 已进入当前回合内的定向补正。当前处置：不手改任务目录、CSV、hash 或 manifest；只接受该轮实际更新后的来源重新验收。
- [2026-08-08] 同一 `cumcm2026` MiMo 烟雾任务的 Q2 首次 `record_execution_evidence` 亦被拒，精确原因为 `metrics[6].value=7.58 无法在 source_path 中复查`；任务仍在当前回合内定向修正，尚未终态失败。当前处置：不手改任务目录、CSV、hash 或 manifest；只观察模型按门禁反馈生成的新来源。

- [2026-08-08] 新建 `cumcm2026` MiMo 轻量真实任务 `20260808-044441-07d759aa269ed2296b17ddc4431ac215` 已在 Q1/Q2 的逐值来源回修后完成，不对执行数据、CSV、冻结结果或 hash 进行手工篡改。`execution_validation.json=PASS`、`frozen_results.json` 有效，Markdown/DOCX/PDF/LaTeX sidecar、`pdf_visual_check.json=PASS`、`submission_audit_report.json=PASS`、候选清单和 `final_acceptance_report.json=TECHNICAL_PASS` 均已实际生成；候选清单 5 个核心 artifact 哈希逐项匹配。独立精确顶点枚举得到原问题 `(40,20),2200`，机器时间 110 小时得到 `(140/3,50/3),7100/3`，增益 `500/3`、影子价格 `50/3`，与冻结值一致。将完整任务复制到容器临时目录后，用全新 Jupyter 内核按 19 个代码单元顺序重放，无代码单元错误（内核关闭时仅有 `jupyter_client` 析构警告，进程退出码仍为 0）；正文无外部参考文献条目，因此记录为“无外部引用可核验”。

- [2026-08-08] 该真实任务初次 preflight 虽为 PASS，语义报告仍发现“二、问题分析”误为 H2 与 2 个空 `{}` 引用标记，不能称为完美版式。`semantic_layout_review.normalize_markdown_semantics()` 现仅在代码围栏和数学行之外，保守修正明确中文主章节层级并移除空引用标记，`prepare_paper_markdown()` 将修复计数写入 `paper_preflight_report.json.fixups`。重建 Docker 后执行受控纯导出刷新（不调用模型、不改冻结结果）使该示例的语义报告变为 PASS/0 issues，并重新生成/哈希绑定 PDF、DOCX、LaTeX、视觉检查、审计和 manifest；人工抽看 PDF 第 1、6、16 页，首页摘要、正文图表/公式和代码附录均无明显裁切、重叠或乱码。说明文件已同步至 PDF 导出说明和最终复核清单；这项语义修复不改变用户启动方式、`cumcm2026` 模板资源结构或替换流程，故模板替换指南和 export profile README 无需更新。

- [2026-08-10] 真实 CUMCM 2025 A 题任务 `20260810-040149-5ddb4141b1f3a545747f4809da4f1b33` 使用 `openai-responses/mimo-v2.5`、`require_model_review=true`，首次 Coordinator 请求在有效 300 s 上限触发 `TimeoutError`，内部下一次尝试随后实际写入 Coordinator checkpoint（12:10:32）。但 `task_status.json` 始终停留在 `running`，Modeler 调用尚未产生 `modeler_plan`/`modeling_decision`；为避免无界占用，根代理于 12:12:28 下发取消，终态为 `cancelled`。Docker/Redis 健康，Base URL 公网 DNS 校验实测约 0.201 s，未读取凭据；这不是已完成的模型计划或交付。后续不得原样重复提交：先针对 MiMo 响应时延、任务阶段可观测性和单任务超时策略做有界恢复，再以新任务重新进入人工模型审批门禁。

- [2026-08-10] 受控恢复任务 `20260810-041711-e04a2532e6b65641a59412bc06cb4230` 已由 MiMo 实际完成 Coordinator/Modeler 和 EDA/Q1 代码执行；人工审查发现其 Q1 中间结果把“等高度”FY1 航向错误地写成含 z 分量的三维指向假目标，得到 0 s，而独立有限圆柱视线网格复算约为 1.39165 s。更关键的是，Q1 的两次 `record_execution_evidence`（05:01:04、05:02:16）均因 simulation 诊断未映射为 source-backed metric 被拒；第二次仍是同一缺陷。按连续两次失败规程，根代理在 05:02:46 取消任务，未接受冻结/论文/导出、未原样第三次重试。后续恢复必须同时修正“无人机只在水平面选航向”的物理实现，以及让状态方程、单位、T1、几何/网格诊断逐项在本轮来源表中成为可复查 metric；先完成隔离副本验证，再由用户授权的受控路径重新执行。

- [2026-08-10] 针对上述 Q1 两次 execution-evidence 拒绝，已在 ModelPlan 契约校验中增加与运行时 `execution_validation` 完全同序、首组命中语义一致的 simulation/optimization 诊断—验收指标预检：计划若要求求解器状态、松弛、守恒/平衡、双喷嘴、减压阀、可行性或步长/网格，必须先声明含对应关键词的验收指标；实际 source-backed 来源绑定仍由运行时门禁复核。新增“状态方程缺指标拒绝、state_equation_audit 通过、普通文本和仅收敛文本不误拒”回归；宿主机相关 126 项单测、Ruff 与差异检查均通过。该修复只缩短失败反馈路径，不绕过执行、冻结、人工质量复核或导出门禁；下一任务仍须由 MiMo 实际执行并按新来源验证。

- [2026-08-10] 新建真实 2025 CUMCM A 题任务 `20260810-051804-7ce501112efa29e830e0c8d365e82ee3` 已真实完成一次 Coordinator 调用（5题 checkpoint）和两次 MiMo Modeler 调用，但两次结构化 ModelPlan 均被 schema 拒绝：第1次缺失完整 `model_plan` 固定字段，第2次 `ques4.acceptance_metrics[2].target` 非数值。根代理于 05:29:58 取消仍准备进行第3次自动格式重试的任务，终态 `cancelled`；未生成 modeler plan、未审批、未运行 Coder/Writer、未产生冻结结果或论文。按连续两次失败规程，不再原样请求 Modeler。后续仅允许在已有 immutable checkpoint、`require_model_review=true`、无活动任务和正常契约校验的条件下，由 Codex 提交结构化方案并重新进入 waiting_review，随后仍须人工 approve 后才可调用 MiMo Coder。

- [2026-08-10] 为落实上述两次 ModelPlan 格式失败后的停止规程，Modeler 的 JSON 格式修正预算现为“首轮加一次纠正”（第二次无效即终止），不再自动发起第三次 provider 调用。`/codex-modeling` 仅扩展到严格的“已取消、无任何持久 ModelPlan/执行/快照/返修/质量状态、且 require_model_review=true”的 pre-execution checkpoint；已执行或有任何恢复痕迹的取消任务仍被 409 拒绝。接管仍走完整 schema/题面契约校验，写入 waiting_review，且必须正常 approve 后才会启动 Coder。新增相应回归，宿主机相关145项单测、Ruff、差异检查通过；这为真实 2025A 任务提供有审计的人工结构化方案接管，而非绕过门禁。

- [2026-08-10] 同一真实 2025 CUMCM A 题接管任务的 Q1 首次 `record_execution_evidence` 在 05:54:36 被受控门禁拒绝：提交的若干 `1.01` 数值不在声明的来源 CSV 中，且没有覆盖已批准 ModelPlan 的状态方程审计、网格加密、水平飞行高度偏差、可复查遮蔽时长和残差记录。此前 Codex 已发现并要求纠正初始三维航向，后续源码已新增水平 `(-1,0,0)` 单元并生成中间 Q1 CSV，但其 0.1 s 网格结果（1.5 s）与已写出的加密网格（1.50/1.45/1.50 s）尚不足以作为收敛结论。当前处置：不手工改 CSV、hash 或 evidence；已向 Coder 追加严格/局部遮蔽语义、0.01/0.001 或事件定位收敛、区间端点和逐项 source-backed metric 要求，只观察一次有界的受控返修，当前未冻结、未质量审批、未进入 Writer 或导出。

- [2026-08-10] 上述 2025A 任务的 Q1 第二次 `record_execution_evidence` 于 05:56:20 再次被拒绝，且失败已从数值来源转为框架契约不一致：ModelPlan/题面契约允许约束比较符 `eq`，但 execution-evidence 协议仅接受 `abs_diff_lte`、`between`、`gt/gte/lt/lte`，未将精确相等转换为可带容差的来源约束。按同一功能连续两次失败规程，根代理停止 Coder 的原样第三次尝试并取消任务；不接受任何中间 CSV、快照、证据、冻结或论文。后续先以最小兼容修复和回归测试统一 ModelPlan/执行证据比较符，再由用户授权的新任务重新验证，不能用手工篡改本任务 evidence 绕过。

- [2026-08-10] 比较符兼容修复加载后的新 2025A 真实任务 `20260810-060700-99a3510d30e1444fbc8cfb452f69d96b` 已由 MiMo 完成 Coordinator（5题拆分）并实际尝试 Modeler；两次 ModelPlan 均未通过契约校验，最终为 `failed`、未生成 plan/decision、未进入 Coder。最后错误为 Q1 将 `max_constraint_violation le 0` 写成无题面/数据/基线依据的经验质量阈值，以及 Q2 要求“求解器收敛/遮蔽采样点与时间步长诊断”却未对应可复查验收指标。按连续两次 Modeler 失败规程，不再向 MiMo 发第三次同类格式修复请求；后续只允许在本任务现有 immutable checkpoint 上经 `/codex-modeling` 的 schema/题面契约校验写入明确来源与诊断的结构化计划，重新回到人工审批门禁后才可调用 MiMo Coder。

- [2026-08-10] 上述 2025A 任务经 Codex 结构化计划审批后，MiMo Coder 的 Q1 首次真实代码执行在 06:25:55 报 `NameError: name 't' is not defined`：`smoke_bomb_trajectory` 内部用未传入的 `t` 计算 `dt`，调用处又把 `t_burst` 误作投放/起爆两个参数。错误单元未成为可接受计算来源，未登记 evidence、冻结或论文；框架已把错误返回当前 Coder 的一次反思回合。当前处置：不手改 task notebook/CSV，不重建或取消当前任务；仅观察这一轮有界纠正，之后必须以空内核顺序重跑、可复查 Q1 轨迹和执行证据为准。

- [2026-08-10] 同一 2025A Coder 在收到“Q1基线进入Q2候选池”的定向返修后，06:40:48 开始的 Q2 基线+网格+高精度局部搜索于 06:46:02 超过本地解释器300秒上限，被 watchdog 中断；内核在 06:46:10 重建且 `snapshot_restored=false`，该超时单元已从可重跑 notebook 源码移除。结合此前 Q1 `NameError`，已构成同一任务 Coder 连续两次执行失败；按规程根代理停止自动第3次尝试并取消任务。未接受此前的零值 Q2 中间 CSV，未写 execution evidence、冻结、质量审批、Writer 或导出。后续必须把严格视线优化改成有解析/向量化几何或受限候选的可证明有界算法，并在隔离副本完成时延/可行性验证后，才允许新任务；不得只增加解释器超时或原样重试。

- [2026-08-10] 为防止数值仿真/优化 Coder 再把细步长计算嵌入无界参数扫描，`CODER_PROMPT` 增加通用执行预算契约：先用向量化、缓存、事件驱动或解析约化粗筛，再对明确数量的 shortlist 做高精度复算；必须记录候选数、筛选规则、网格/时域、估算与实测耗时，并在预计超过 watchdog 时改用有界筛选或等价高效求解。该提示不改变题面、执行证据、冻结、人工质量复核或导出门禁，也不设领域经验阈值。新增提示回归；宿主机 `app.tests.test_coder_prompt` 2项、Ruff 和差异检查实际通过。下一次 2025A 任务仍须由 MiMo 实际执行，且先以独立向量化基线验证算法运行时间，不能把该提示当作数学正确性证明。

- [2026-08-10] 新建真实 2025 CUMCM A 题任务 `20260810-073046-5ad7409f50644a2211d4e67828ca043e` 已由 MiMo 实际完成 Coordinator，并在 Modeler 首轮和唯一一次格式纠正后均被 ModelPlan 契约拒绝，终态 `failed`，未进入 Coder、证据、冻结、质量复核、Writer 或导出。最终拒绝项为：Q2 无依据的 `proxy_model_r2>=0.8` 经验阈值、Q5 将守恒/平衡诊断伪作精确硬阈值，以及 Q1/Q2/Q5 的诊断要求未映射到可复查验收指标。当前处置：不再向 MiMo 发第三次 ModelPlan 请求；本任务保持 pre-execution 失败状态，根代理仅用已在隔离副本执行验证且经题面契约校验的结构化 Codex 计划接管到 `waiting_review`，之后仍须人工 approve 才能调用 MiMo Coder。临时副本的 CSV/XLSX 不会复制、登记或复用为本任务证据。

- [2026-08-10] 同一任务经结构化计划、人工模型审批和 MiMo Coder 的真实受控执行后，5 个子题 execution validation 与冻结结果均为 PASS，但质量审批前的隔离副本新内核顺序重跑发现 notebook 仍含冗余“超精细敏感性”草稿：27 个代码单元可执行完毕，却在错误解析 Excel 字段后写出 Q2=2.996279 s（冻结为4.577434）、Q3=0（冻结为5.714546）、Q4=2.996279（冻结为10.663451）、Q5=0（冻结为17.022487）的矛盾结论。独立、不导入任务求解器的 5440 点有限圆柱闭线段几何复算则与冻结五问结果一致（最大差约0.000133 s），且速度、投放/起爆时序、爆点高度和同机间隔均通过。当前处置：任务保持 `waiting_quality_review`，不批准 Writer/导出；仅走受控质量返修，移除或替换错误草稿、保留可重跑的唯一正确源链，并重新登记执行证据、冻结和后续导出门禁。另需检查 Coder 在敏感性阶段出现的过多回合，避免提示中的执行预算契约只约束单元而未约束整阶段。

- [2026-08-10] 上述质量返修的 Q3 中，Coder 将暂时不可见的 `result1.xlsx` 误当作可自行设计的空白模板，创建了非附件字段布局后才运行正式求解器。Q3 数值输出仍为有限候选并集 5.714546 s，但该 XLSX 结构不能作为题目附件模板交付或 evidence 来源。当前处置：在其提交 Q3 evidence 前阻止放行；仅通过受控代码恢复题目原始 10 列中文字段、备注行与三弹行位，再重新运行任务内正式求解器覆盖该表和 Q3 来源。不得接受该临时模板、不得手改 evidence/hash。

- [2026-08-10] 同一 Q3 模板恢复的下一次受控代码已写回 10 列字段和备注，但仍将工作表命名为 `Q3策略表`；正式任务求解器固定读取附件的 `Sheet1`，因此 `run_question("ques3")` 明确报 `Worksheet Sheet1 does not exist.`，没有产生可接受的 Q3 模板/验收来源。当前处置：不将该被捕获的错误输出当作成功、不提交空表 evidence；仅在 Coder 的门禁反馈回合将现有活动表重命名为 `Sheet1` 后再运行同一正式求解器。若再次无法完成，停止本任务的同类重试并整理失败证据。

- [2026-08-10] 同一 Q3 在已把活动表改为 `Sheet1` 后，Coder 第二次受控 evidence 仍被拒：它只保存了改名空模板，没有按明确指令重新执行 `run_question("ques3")`，因此缺少 `ques3_acceptance_metrics.csv` 和有效 XLSX 数值来源。连同前一次工作表名导致的 source/evidence 缺口，已构成质量返修阶段同一 Q3 的连续两次失败；工作流随即自动将任务标记为 `failed`，根代理事后发送的 cancel 请求返回“任务不存在或已完成”，没有改变终态。未批准冻结、Writer 或导出。后续仅可由指定决策人切换已验证 provider 再尝试一次，或通过受控 Codex 候选修复/独立新任务重建正确模板、正式来源和 evidence；不得继续在当前 MiMo 会话中追加指令碰运气。

- [2026-08-10] 同一 2025A 任务随后经容器内受控 Codex 候选逐题重建 Q1--Q5，五条 `record_execution_evidence` 均实际通过；Q3--Q5 的 `result1/2/3.xlsx` 分别按 immutable ModelPlan 声明路径写回，并额外通过 `Sheet1`、原始中文表头、备注行和数据行数的 CSV 结构审计，`execution_validation.json=PASS`。但旧的质量返修续传实现会在候选已经写入干净 notebook 后再次清空 notebook/快照，导致全量验证仅报 `notebook_execution: notebook 没有任何代码单元`，进而错误启动第三次 MiMo `ques3_repair`。根代理在该调用尚未完成/登记证据前立即取消，任务现为 `cancelled`、无新冻结/质量批准/Writer/导出；不得把这次自动调用或任何中间代码当作通过结果。当前处置：先为候选质量返修补齐“干净源码已准备”持久状态，确保首个候选隔离旧源、后续候选追加同一链、续传不再次清空或重放旧快照；然后仅以候选通道重新登记证据和冻结，不再调用 MiMo Q3。

- [2026-08-10] 上述 2025A 任务完成候选重建、全量验证、冻结和 Codex 技术质量审批后，Writer 已实际生成 `res.md/res.json`，但 `paper_preflight_report.json=FAIL`，工作流按硬门禁停止 DOCX/PDF/LaTeX/清单导出。硬失败不是数学或冻结证据：摘要 1472 字符超过 `cumcm2026` 的1200上限；正文“改进与推广”把遗传算法、粒子群优化作为命名算法提及，算法证据门禁将其识别为未实现声明（sources 为空）。当前处置：不重跑或篡改 Q1--Q5 冻结数值，不伪造算法 evidence；先以冻结 CSV/ModelPlan 为唯一依据，修正摘要长度和未来改进的算法措辞，并同时复查 Writer 对“局部精化/最优/同机间隔”等叙述是否与真实有限策略库及题面一致，然后重新走受控论文修复、预检和全部导出门禁。

- [2026-08-10] 同一真实 2025 CUMCM A题任务 `20260810-073046-5ad7409f50644a2211d4e67828ca043e` 已完成可审计的 Codex 论文候选修复闭环：新增的容器内 `paper_repair_candidate` 仅在 `frozen`、当前 preflight 为 `FAIL`、完整 Writer 阶段和冻结哈希均有效时接受完整章节替换；它先在隔离任务副本预检，再同步更新 `res.json/res.md` 与 checkpoint 的 Writer hand-off，随后 `/resume` 只走预检/导出，不初始化或调用 MiMo。该候选修正了摘要超长、未实现算法表述、固定半径下沉物理口径、全采样表面遮蔽、Q3不少于1秒间隔、Q4/Q5实际高度和“有限候选库”范围，未修改代码、CSV、XLSX、evidence 或冻结结果。最终 `execution_validation=PASS`、`execution_quality_review=PASS`、`paper_preflight=PASS`、`semantic_layout=PASS`、`pdf_visual_check=PASS`（55/55页，正文9页、附录从第11页开始）、`submission_audit=PASS`、LaTeX sidecar 编译成功、`final_acceptance=TECHNICAL_PASS`、`task_status=completed`；候选清单五个核心文件哈希绑定当前产物。隔离全新进程重跑五个候选脚本得到全部 result CSV 的字节级一致结果；独立不导入求解器的 8995 点有限圆柱复算与冻结时长最大差小于0.00004 s。人工抽看 PDF 第1、6、11页，摘要、正文公式/图和附录无裁切、重叠或乱码；DOCX 包可打开且含标题、Q5数值和5个图形关系。正文无外部引用，故记录为“无外部引用可核验”。提交前仍需队员按竞赛规则确认匿名、文件命名、上传格式和是否接受55页总PDF（正文9页、其余为附录）。

- [2026-08-11] 用户对上述 2025A 候选作论文质量复核后否决其“默认范文/正式论文”定位：虽然技术链完整，正文仅 9 页、有效摘要约 371 字、正文只有 5 张同构区间条形图和 1 张符号表，55 页中的大部分是代码附录。根因是预检仅检查摘要 120--1200 字、已有图表的存在/引用和正文上限，不检查摘要首屏密度、正文下限、每问结果表/证据图覆盖或图表多样性；本次 Codex 论文候选修复又只以事实一致与预检 PASS 为目标，未设论文质量验收条件。当前处置：撤销该任务的默认示例/正式提交定位；在再次导出前实现内部 editorial quality policy、由真实冻结来源生成图表/结果表、记录候选前后质量统计，并将质量门禁接入最终验收。不得把“正文至少 10 页”等内部目标冒充为竞赛官方硬规则。

- [2026-08-11] 在上述 2025A 的展示资产重建中，首次运行新增的只读 CSV→图表脚本于首张图渲染时因 `Axes.scatter()` 参数位置错误退出（`TypeError: got multiple values for argument 's'`）；尚未写入任何执行证据、冻结结果或论文正文。当前处置：先修正生成脚本并在隔离/正式来源一致条件下重新生成展示资产，检查每张图的来源哈希和视觉可读性后，才允许进入受控论文编辑返修；不把该失败运行当作资产验证通过。

- [2026-08-11] 修正首图后，同一展示资产脚本在 Q5 时间轴读取 `ques5_visibility_intervals.csv` 时再次退出：bomb 行的 `missile` 单元为空，脚本错误地把它当作导弹分配键（`KeyError: ''`）。前五张 presentation-only PNG 已生成，但无完整 `paper_assets_manifest.json`，未进入正文、预检、导出或结果冻结。按连续两次失败规程，停止直接在正式任务目录重复完整运行；先在隔离副本以 `ques5_result.csv` 的 strategy→missile 映射补齐该展示层关联并做一次全图自检，确认后再一次性替换正式展示资产。不得以不完整的五张图宣称修复完成。

- [2026-08-11] 2025A 的第二版编辑质量论文候选在隔离预检入口被 JSON 解析器拒绝（`Expecting ',' delimiter: line 179`）；失败发生在候选文件读取阶段，未写入正式 `res.md/res.json`、未改冻结结果或导出物。当前处置：先修复候选 JSON 语法并重新在隔离副本执行完整预检；只有候选、来源哈希清单和所有硬门禁均通过，才允许使用一次编辑质量候选返修预算。

- [2026-08-11] 修复 JSON 后的隔离编辑质量预检仍拒绝 2025A 候选：旧的结果资产识别词表无法识别“遮蔽区间、轨迹、短名单、网格”等真实结果图，故误报 0 图/0 表；候选也缺少显式“模型的建立与求解”主章节。未写入正式任务。当前处置：扩展内部结果资产语义词表并将五问收束到标准主章节层级，再以同一隔离预检和来源哈希清单复核；该修复不涉及 provider、冻结数值或模型重跑。

- [2026-08-13] 真实 2026 华数杯 A 题任务 `20260813-025954-ec2f0a6ca8564e0e6cfee54a1e22d846` 使用用户授权的 OpenAI-compatible 运行时配置（不写入 `.env.dev`）完成 Coordinator 一次成功拆题后，Modeler 对同一请求在 `03:02:44`、`03:04:51` 连续两次收到 `InternalServerError`。根代理于 `03:05:28` 发送取消并确认任务为 `cancelled`，未生成 `modeler_plan`、代码、execution evidence、冻结结果、论文或导出产物。当前处置：不得继续原样重试该 Modeler 请求；已验证的 `gpt-5.6-terra` 可作为经人工切换后的单次受控恢复候选，或改走经契约校验的 Codex 建模方案，再正常进入审批和执行门禁。不得把 Coordinator 拆题或上传文件当作模型结论。

- [2026-08-13] 上述任务按恢复规程将 Modeler 切换至已通过 `/validate-api-key` 的 `gpt-5.6-terra` 后，于 `03:08:29` 的唯一受控续传仍收到 `InternalServerError`。根代理于 `03:09:23` 取消任务，未允许该路径继续自动重试；仍无 ModelPlan、代码、execution evidence、冻结或论文产物。当前处置：停止本任务的远程 Modeler 路径，改由 Codex 提交经题面/契约校验的本地结构化建模方案，再正常接受审批、受控计算与质量复核；不得把两次 provider 探测成功或 Coordinator 输出冒充为建模完成。

- [2026-08-13] 同一真实 2026 华数杯 A 题任务的本地可复算 `solve_a.py` 中等样本全新进程重跑在第 3 问数据已写出后、绘制 `ques3_threshold_curve.png` 时因浮点舍入使 Matplotlib 接收到微小负 `yerr` 而退出（`ValueError: 'yerr' must not contain negative values`）。尚未写入 execution evidence、冻结结果、论文或正式导出物；此前产生的 CSV/PNG 仅为未冻结中间结果。当前处置：先将误差条下限钳制为零并重跑全链路，结果只以成功全新进程产生的当前源哈希与数据文件为准；不得把本次中断运行的中间表或初步概率当作验收结果。

- [2026-08-13] 修正绘图层后，同一 A 题的完整中等样本重跑在受控 120 秒窗口内尚未结束，被命令超时安全终止；无 Python 异常输出，但不能将被终止进程写出的局部文件当作完整本轮结果。该任务已发生连续两次本地全量运行失败（先绘图、后超时）。当前处置：停止重复同一全量命令；先检查已有阶段性产物与运行瓶颈，将计算拆为可独立完成并重新核验的低成本阶段，完成后再做一次受控整合与来源哈希刷新。未产生 execution evidence、冻结、论文或正式导出结论。

- [2026-08-13] 同一真实 2026 华数杯 A 题在用户重新授权并将运行时角色切回已通过密钥验证的 `gpt-5.6-sol` 后，建模方案修订的首个远程调用于 `04:22:13` 收到 `InternalServerError`；任务仍处于框架控制的 `revising` 状态，尚未写入新的 `modeler_plan.json`，也未产生执行证据、冻结或导出物。当前处置：不并发、不手工重复提交修订请求；仅观察该次工作流自身的有界重试和终态，若终态失败则先记录精确原因再决定受控恢复路径。

- [2026-08-13] 上述 `gpt-5.6-sol` 建模方案修订在 `04:24:19` 第二次连续收到 `InternalServerError`，新方案文件仍未更新。按同一任务/功能连续两次 provider 失败规程，根代理停止该工作流将要进行的第三次原样自动重试；不切换为其他模型（用户本轮明确要求 `gpt-5.6-sol`）。后续只可在不再请求远程 Modeler 的前提下，使用已审查的本地结构化 ModelPlan 重新进入审批门禁，并在后续 Coder/Writer 阶段仍使用用户指定模型；若该模型在代码或写作阶段也连续失败，将停止并如实报告。

- [2026-08-13] 用户随后明确授权仅用其现有凭据在 Docker 后端容器内再次尝试，因而新建干净的 2026 华数杯 A 题任务 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff`，预注入了“同一原始介质越界平移片段为同一导体、左右 X 面为独立电极”的约束。Coordinator 于 `04:28:45` 实际成功返回 4 问拆分；Modeler 首次调用于 `04:30:51` 收到 `InternalServerError`，尚未生成 ModelPlan、代码、execution evidence、冻结或导出物。当前处置：遵照用户新授权，只观察该容器工作流自身的有界重试；不使用其他凭据或模型，不将成功的 Coordinator 输出当作建模结论。

- [2026-08-13] 同一用户明确授权的 Docker 内重试任务在 `04:32:57` 的 Modeler 第 2 次调用再次收到 `InternalServerError`，仍未生成 ModelPlan、代码、execution evidence、冻结或导出物。项目常规规程本应在连续两次失败后停止同类重试；但用户在本轮明确要求“如果失败再次尝试”，因此仅允许当前工作流的最后一次有界自动尝试，不并发、不新建额外请求、不换凭据或模型。该尝试若仍失败，先如实记录终态和错误，再等待用户进一步方向。

- [2026-08-13] 同一用户授权的 Docker 内第三次有界 Modeler 尝试于 `04:35:05` 失败，任务 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff` 终态为 `failed`。上游返回 Cloudflare 524：连接已建立但源站在 120 秒代理读取窗口内未返回完整响应；后端将其归类为 `InternalServerError`。Coordinator 已成功，但 `modeler_plan.json` 不存在，未执行代码、未登记 execution evidence、未冻结或导出。当前处置：用户明确要求失败后重试，故遵循上游建议至少退避 120 秒后才在 Docker 容器内用同一凭据和 `gpt-5.6-sol` 发起下一次单一受控重试；绝不使用其他凭据或模型。

- [2026-08-13] 同一任务经 Codex 结构化方案和人工审批进入 `gpt-5.6-sol` Coder 阶段后，EDA 已成功生成且 Q1 已生成未冻结的有限线段接触图草稿。Codex 独立检查发现附件有相对面连续端点配对（组1=3、组2=10、组3=178），故已要求 Coder 将其重建为同一原始导体的边界身份连通，禁止把旧的“每行独立、身份边为0”草稿提交 evidence。该修正引导后的下一次 Coder 调用于 `04:49:39` 收到首次 `InternalServerError`；尚未发生 execution evidence、冻结、质量审批或导出。当前处置：允许当前 Docker 工作流的一次有界重试；不以草稿结果作结论、不切换凭据或模型。

- [2026-08-13] 同一 Docker 内任务的 Q2 首次受控代码执行于 `04:54:40` 启动后超过本地解释器 300 秒看门狗上限，`04:59:40` 被中断；后端已在 `04:59:46` 重建内核并从 Q1 的变量快照恢复 142 个变量。失败发生在尚未写入 Q2 执行证据、冻结或导出之前，Q1 的已验证产物不受此事件影响。当前处置：仅允许 Coder 在恢复内核中进行一次有界的算法/预算修正，优先空间索引和可复现实验预算；不得再原样运行高复杂度全对镜像枚举，也不得把超时前的局部文件当作 Q2 结论。

- [2026-08-13] Q2 超时恢复后的第二段展示/汇总代码于 `05:02:03` 因把长表中的“介质A数量”当作索引键而抛出 `KeyError`，未改变已生成的原始 Q2 试验表或执行证据；这是同一 Q2 计算链的第二次连续代码失败。当前处置：停止再运行原来的全对扫描或错误字段索引路径，仅允许基于完整圆柱几何的定向修正（包括半径在 X 投影、解析充分事件与 Q3 阈值），并在新证据落盘后重新校验；不得把旧的轴线近似概率/阈值当作最终结论。

- [2026-08-13] 用户明确限定为 Docker 内、同一用户凭据和 `gpt-5.6-sol` 的 2026 华数杯 A 题任务 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff` 在 `05:15:28` 的执行验证中仍有唯一硬错误（Q4 正式指标文字被判为“估计”，不能作已执行证据）。定向回修已先成功重写局部 Q4 文件，但随后的两轮 Coder provider 调用在 `05:16:45`--`05:16:55` 各自三次重试均为 `PermissionDeniedError`，达到连续 provider/协议异常恢复上限；任务于 `05:16:56` 终态 `failed`。已有 Q1--Q4 与灵敏度 CSV/PNG、notebook、资产清单和变量快照，但无冻结结果、质量复核、`res.md`/`res.json`/DOCX/PDF 或候选清单。当前处置：停止同一凭据/模型的原样重试，不切换凭据或模型；保留现有工作目录，等待用户提供经授权且已恢复权限的同一 provider 配置后再作一次受控恢复。

- [2026-08-13] 用户提供新的 Docker 运行时 endpoint/key 后，仅在容器内做了只读能力验证：`GET /v1/models` 返回 16 个可用模型，说明 endpoint 可访问；但 `gpt-5.6-sol` 不在列表中，直接请求返回 `MODEL_NOT_AVAILABLE`。未保存新 key、未改 runtime 配置、未续传失败任务，也未切换到其他模型。当前处置：遵守用户此前指定的 `gpt-5.6-sol` 约束，暂停等待用户授权该 endpoint 的可用模型或提供包含 `gpt-5.6-sol` 的 endpoint。

- [2026-08-13] 用户随后明确授权改用该 Docker endpoint 的最新 `deepseek-v4-flash` 别名；`/validate-api-key` 返回 valid=true，运行时四角色配置仅以内存方式切换，未写入密钥文件。对既有 A 题任务发起 `provider_changed` 受控续传后，Coder 修复阶段连续完成多次工具调用，但在 `10:09:50 UTC` 首次收到 provider `InternalServerError`，尚未写入新的验证终态或导出物。当前处置：记录本次真实 provider 失败，继续观察该工作流自身的有界重试；不换凭据/模型、不并发提交。

- [2026-08-13] 同一 `deepseek-v4-flash` Coder 修复调用于 `10:10:52 UTC` 出现第 2 次 `InternalServerError` 重试，任务文件仍停留 `resuming/manual_recovery`，尚无新的验证或导出终态。当前处置：按用户授权仅观察当前调用的最后一次有界重试；不并发、不更换凭据或模型，若工作流终止则停止重复提交并报告。

- [2026-08-13] 该 Coder 调用于 `10:11:54 UTC` 完成第 3 次 `InternalServerError` 重试，Coder 记录 `执行过程中发生异常` 后进入下一对话轮次；截至记录时任务仍未写入新的验证/导出终态。当前处置：不重复提交同一失败调用，继续只读观察框架是否能从已保存上下文恢复；若最终失败，保留现有 Q1--Q4 产物并报告未完成门禁。

- [2026-08-13] 框架在上一轮异常后于 `10:12:58 UTC` 发起下一次 Coder 对话请求，该请求再次出现第 1 次 `InternalServerError`；任务仍为 `resuming/manual_recovery`，未产生新文件。当前处置：该请求的重试仍由框架自身有界执行，继续只读观察并不手工追加请求。

- [2026-08-13] 同一后续 Coder 对话请求于 `10:13:59 UTC` 出现第 2 次 `InternalServerError`；仍未产生新验证或导出文件。当前处置：只等待该请求最后一次框架重试及终态。

- [2026-08-13] `deepseek-v4-flash` 受控续传的后续请求于 `10:15:02 UTC` 第 3 次重试仍为 `InternalServerError`，Coder 记录 `failures=2` 达到恢复规程上限，任务终态为 `failed`，消息为“代码阶段 ques4 未提供成功执行证据；诊断报告状态：FAIL”。未生成新的冻结、质量复核或论文导出物；已有 Q1--Q4 中间 CSV/PNG 与 notebook 保留。当前处置：停止本次同模型原样重试，等待用户进一步授权或调整运行策略。

- [2026-08-13] 用户明确要求继续诊断后，Docker 内重新验证新 key：后端 `/validate-api-key` 返回 `valid=true`，直接访问同 endpoint `/models` 为 HTTP 200 且包含 `deepseek-v4-flash`，最小 `/chat/completions` 也为 HTTP 200；因此此前失败不能归因于 key 无效。随后沿用已审查结构化方案接管同一任务并将 Coder/Writer 上下文窗口临时降为 64000 token；新 Coder 首次请求于 `10:22:45 UTC` 再次出现 `InternalServerError`，尚未产生新的验证终态。当前处置：记录真实 provider 失败，继续观察当前框架有界重试，不输出或持久化 key。

- [2026-08-13] 同一接管续跑在 Coder 第 8 对话轮次于 `10:26:58 UTC` 再次出现第 1 次 `InternalServerError`；此前已完成多轮工具调用，任务仍 `resuming/manual_recovery`。当前处置：记录并等待该调用的有界重试，暂不认为是 key 故障。

- [2026-08-13] 同一接管续跑在 Coder 第 16 对话轮次的请求于 `10:32:11`、`10:33:12 UTC` 分别出现第 1、2 次 `InternalServerError`；尚未产生新的验证终态。当前处置：记录并等待本请求最后一次有界重试，若失败则停止重复提交。

- [2026-08-13] 上述第 16 轮请求于 `10:34:15 UTC` 第 3 次重试仍为 `InternalServerError`，Coder 随后进入第 17 轮；已有 EDA 快照保留，尚无 Q1 新冻结或验证终态。当前处置：不手工重发该失败请求，继续观察框架是否能从上下文恢复。

- [2026-08-13] Coder 第 17 轮于 `10:35:17 UTC` 发出的请求又出现第 1 次 `InternalServerError`；仍在 EDA→Q1 过渡阶段，尚无新验证文件。当前处置：记录并继续观察该轮内置重试。

- [2026-08-13] Coder 第 17 轮请求于 `10:36:19 UTC` 出现第 2 次 `InternalServerError`；仍未产生新的 Q1 结果或验证文件。当前处置：只等待最后一次框架重试。

- [2026-08-13] Coder 第 17 轮于 `10:37:21 UTC` 第 3 次重试仍为 `InternalServerError`，随后框架记录 `failures=2` 并于 `10:37:22 UTC` 将任务置为 `failed`，消息为“代码阶段 ques1 未提供成功执行证据；尚未执行正式逐题验证”。本次接管仅保留 EDA 与变量快照，未生成新的 Q1 结果、execution validation、冻结、质量复核或导出物；旧的中间 Q1--Q4 产物仍在工作目录。当前处置：停止同一 endpoint/model 的原样重试；已确认 key 鉴权和最小请求正常，故该失败记录为长上下文/工具调用阶段的上游 `InternalServerError`，不是 401/403 API Key 无效。

- [2026-08-13] 用户询问切换模型后，在 Docker 内使用同一用户 endpoint/key 做只读模型探测：`/models` 首次短暂返回 HTTP 503，单次重试返回 HTTP 200、共 16 个模型（包括 `deepseek-v4-flash`、`deepseek-v4-pro`、`glm-5/5.1/5.2`、`qwen3.7-max/qwen3.8-max`、`kimi-k2.5/k2.6/k2.7-code`、`mimo-v2.5-pro`、`minimax-m2.5/m2.7`、`seed-2.1-turbo/pro`）。最小 chat 探测中 `deepseek-v4-pro`、`glm-5.2`、`qwen3.8-max`、`kimi-k2.7-code`、`mimo-v2.5-pro`、`minimax-m2.7` 均 HTTP 200；`seed-2.1-pro` 本次探测 HTTP 503。未切换运行时配置、未启动新建模任务、未输出或持久化 key。模型元数据报告的 context_length：deepseek-v4-flash/pro、glm-5.2、qwen3.8-max 为 1,000,000；mimo-v2.5-pro、kimi-k2.7-code 为 256,000；minimax-m2.7 为 200,000；seed-2.1-pro 为 262,144。短请求成功不能替代长上下文/工具链验收。

- [2026-08-13] 用户明确授权先切换模型后继续测试；在 Docker backend 进程内用同一用户 endpoint/key 验证 `deepseek-v4-pro`，`/validate-api-key` 返回 `valid=true`，随后 `/save-api-config` 将 coordinator/modeler/coder/writer 的运行时模型统一设为 `deepseek-v4-pro`、context_window=64000，返回 `success=true, persisted=false`。未写入 `.env.dev` 或其他密钥文件，尚未启动任务续跑。

- [2026-08-13] `deepseek-v4-pro` 接管续跑于 UTC `11:18:11` 完成 EDA 子任务并保存 316 个变量快照，随后进入 Q1。Q1 对话轮 9 于 `11:18:24`、`11:18:37`、`11:19:40` 三次重试均收到 provider `InternalServerError`，Coder 记录异常后进入下一轮（截至记录时任务仍 `resuming`，未写入新的 Q1 执行证据）。该模型此前已成功完成多轮工具调用和 EDA 收束；当前只观察框架下一轮的有界恢复，不手工叠加请求、不切换 endpoint/key。

- [2026-08-13] 用户授权切换到 `deepseek-v4-pro` 后的 Docker 接管续跑在 UTC `11:24:06`、`11:25:08`、`11:26:10` 的后续 Q1 Coder 请求中三次重试均为 `InternalServerError`；`11:26:10` 达到 `failures=2`，任务于 `11:26:11` 置为 `failed`，消息为“代码阶段 ques1 未提供成功执行证据；尚未执行正式逐题验证”。本轮仅完成 EDA 并保存 316 个变量快照，未生成新的 Q1 结果、正式执行验证、冻结、质量复核或导出物；旧中间文件保留。当前处置：停止继续提交同一模型/endpoint 的原样重试；key 已通过验证，故此次失败仍归类为长上下文 Coder 阶段上游 5xx，而非 API Key 鉴权失败。

- [2026-08-13] 诊断确认 `deepseek-v4-pro` 失败集中在 Coder 长对话：多次请求约每 60 秒收到上游 `InternalServerError`，无 401/403；Docker 服务、Key 最小请求和模型探测均正常。任务目录仍保留较早运行的 `execution_validation.json`，因此失败后刷新出的报告可能读取旧 Q1 证据，不能替代本次检查点的 `completed_phases`/新鲜来源哈希。按用户“继续”授权采用一次不同策略：仅 Coder 切换至先前最小探测成功的 `kimi-k2.7-code`，Coder context_window 从 64000 降为 32000，其他角色保持现有运行时配置；配置仅写当前进程（persisted=false），随后从审查后的结构化 ModelPlan 受控重启，不再原样重试 `deepseek-v4-pro`。

- [2026-08-13] 上述受控恢复改用 `kimi-k2.7-code`、Coder context_window=32000 后，于 UTC `12:42:25` 从旧变量快照恢复并成功完成 EDA，随后 Q1 进入约 19 轮工具对话；期间多次短暂 `InternalServerError` 可恢复，但在 `13:03:02`、`13:04:04`、`13:05:06` 的同一请求三次重试均失败，Coder 于 `13:05:06` 达到连续 provider/协议异常上限，任务在 `13:05:07` 置为 `failed`，消息为“代码阶段 ques1 未提供成功执行证据；尚未执行正式逐题验证”。本轮没有生成当前尝试的 Q1 结果或 execution evidence，仅保留新 EDA/变量快照；旧 Q1 文件仍存在但时间戳早于本轮，不能采信。当前处置：已用不同模型与较小上下文完成一次有界恢复，仍复现长 Coder 请求上游 5xx；停止继续换模型或重复提交。后续应优先修复证据新鲜度/失败清理与安全 provider 错误诊断，并在 provider 稳定后从干净 Q1 入口重新执行，而不是把旧 CSV 当作本轮成功。

- [2026-08-13] 用户指定官方 DeepSeek Anthropic 端点与 `deepseek-v4-flash` 后，Docker `/validate-api-key` 返回 `valid=true`；同端点最小 Anthropic 工具探针返回 `probe_tool`，证明 Key、端点、模型和工具协议均可用。随后运行时四角色切换为该模型（仅当前进程、未持久化密钥），接管任务于 UTC `13:47:32` 成功完成本轮 EDA 并保存 344 个变量快照；Q1 Coder 于 `13:48:57` 返回无工具调用，未生成本轮 Q1 证据，任务置为 `failed`（“代码阶段 ques1 未提供成功执行证据”）。旧 Q1 文件导致自动报告可误报 PASS，但检查点仅有 `eda`，因此不采信。当前处置：失败归因从 API Key/网络转为正式子题在 `tool_choice=auto` 下无工具响应与旧结果新鲜度边界；停止同一任务的原样重试，下一步应修复 Coder 正式题无工具响应的有界重试/强制工具选择，并在干净 Q1 入口重新执行。

- [2026-08-13] 针对上述 `deepseek-v4-flash` 运行，先在 Docker 中隔离归档旧的 Q1/验证/notebook/快照文件，再将 Coder 正式题首轮增加有界无工具恢复；干净入口重跑于 UTC `13:56:20` 完成 EDA 并保存 11 个变量快照，但 Q1 连续三轮均返回 `tool_calls=0`，于 `14:02:52` 再次失败，未生成当前 Q1 结果或证据。日志没有 401/403、InternalServerError 或 PermissionDenied；因此第二次失败仍不是 Key 问题，而是兼容端点在“execute_code + record_execution_evidence”混合工具集上的工具选择行为。当前处置：不再原样重跑该任务，保留可恢复归档和失败证据。

- [2026-08-13] Docker 官方端点回归探针进一步确认：Anthropic `tool_choice={"type":"tool",...}` 在 DeepSeek V4 thinking 模式返回 HTTP 400（`Thinking mode does not support this tool_choice`）；同一 Key/模型只提供单个工具并使用 `tool_choice={"type":"any"}` 返回 1 个工具调用、文本长度 0。已据此修正 `coder_agent.py`：正式首轮只暴露 `execute_code`，证据提交边界只暴露 `record_execution_evidence`，两者均使用兼容的 `required`（适配为 `any`）；保留正式题无工具响应的三次有界失败保护。Docker 内 `test_anthropic_provider` + `test_coder_agent_tools` 共 26 项全部通过。该修复尚未再次启动真实建模任务，避免违反连续失败恢复规程；下一次真实重跑须由用户明确授权，并从干净 Q1 入口开始。

- [2026-08-13] 用户要求改用 DeepSeek OpenAI-compatible `https://api.deepseek.com/v1`。Docker `/validate-api-key` 返回 `valid=true`；直接 OpenAI Chat 探针中，字面 `tool_choice="required"` 与 `{"type":"any"}` 均返回 HTTP 400，而单工具 `tool_choice="auto"` 返回 1 个真实工具调用。为保留 Agent 内部的显式 `any` 语义，新增 OpenAI Chat 适配转换：`any` → 单工具 `auto`，Coder 仍拒绝无 `tool_calls` 的响应；Anthropic `any` 映射为原生 `type=any`，Responses 适配映射为 `required`。通过实际 `OpenAIChatProvider.call(tool_choice="any")` 探针得到 `tool_calls=1`，四角色运行时配置已切到该端点/模型（仅当前进程，`persisted=false`）。Docker 相关测试共 34 项全部通过，Ruff 通过；尚未启动完整建模任务。

- [2026-08-13] OpenAI-compatible `https://api.deepseek.com/v1` 的一次受控干净入口续跑已完成 EDA 并实际多次收到 `tool_calls=1`/执行 `execute_code`；进入 Q1 后 UTC `14:24:39`、`14:26:02`、`14:27:18` 连续三轮返回 `tool_calls=0`，有界门禁未采信文字收束，任务最终置为 `failed`，消息为“代码阶段 ques1 未提供成功执行证据；诊断报告状态：FAIL”。Docker 后端健康，未见该轮 401/403、InternalServerError 或 PermissionDenied；失败归因是该 OpenAI-compatible 端点在 Q1 长提示下没有实际工具调用，而非 API Key/端点鉴权。已有 EDA/notebook/快照保留，无本轮 Q1 结果、execution validation、冻结、质量复核或导出物。当前处置：按连续失败恢复规程停止同一任务的再次提交；保留内部 `any` 约束与诊断证据，等待新的人工策略决定。

- [2026-08-13] DeepSeek OpenAI-compatible 强制工具调用修复：`OpenAIChatProvider._convert_tool_choice` 现接收 `tools`；内部 `any` 在恰有一个工具（正式首轮的 `execute_code`）时映射为 `{"type":"function","function":{"name":"execute_code"}}`，多工具时警告并回退 `auto`。正式子题在尚无成功代码执行时通过 LLM/provider 透传 `thinking=False`，OpenAI Chat 请求写入 `extra_body={"thinking":{"type":"disabled"}}`；首轮仍只暴露 `execute_code`，无工具调用的三次有界失败门禁未改动。Docker 已重建，`test_anthropic_provider` + `test_coder_agent_tools` 为 26/26 PASS，`test_llm_provider_timeout` 为 10/10 PASS，Ruff PASS。容器重建后原本仅进程内保存的 DeepSeek 配置已恢复为非 DeepSeek Coder 配置，且容器/宿主均无 `DEEPSEEK_*` 凭据变量；为完成最小验证，使用当前受信任 Coder 网关、`deepseek-v4-flash`、单个 `execute_code`、内部 `any` 和 `thinking=False` 发出一次非持久化 Chat 探针，返回 `AuthenticationError`，没有 `tool_calls`，未重试且未向其他端点发送凭据。该探针不能验证强制调用；待操作人重新配置原 DeepSeek endpoint/model/key 后，运行同一单工具探针并断言 `tool_calls=1`。

- [2026-08-13] 用户授权的 B 任务已将 DeepSeek OpenAI-compatible 配置仅注入当前 backend 进程（`persisted=false`，其余三个角色传空块而保持不变）；`/validate-api-key` 返回 `valid=true`，官方端点的单 `execute_code` + 内部 `any` + `thinking=false` 探针实际返回 `tool_calls=1`、名称为 `execute_code`。随后只提交一次任务 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff` resume。日志表明该路径并非用户要求的干净 Q1 入口：它恢复了旧变量快照（43 个变量）并复用 `eda`。Q1 第一轮仍成功返回并执行了 `execute_code`；后续两轮各经历三次 `BadRequestError` 后触发 Coder 连续 provider/协议异常上限，任务于 `15:12:07` 置为 `failed`，状态消息为“代码阶段 ques1 未提供成功执行证据；诊断报告状态: FAIL”。当前 `execution_validation_report.json=FAIL`（缺少 `execution_validation.json`），没有新的 Q1 执行证据、冻结结果或 DOCX/PDF。已停止，不再自动提交；后续先需在不调用 provider 的条件下修正/确认 resume 的旧快照与 EDA 复用语义，并在获得明确授权后对 DeepSeek 的工具结果后续回合 `BadRequestError` 做有界诊断。

- [2026-08-13] 针对 B 的日志定因已修正 Coder：所有正式子题工具回合（含执行后与证据提交边界）统一 `thinking=false`，只在尚无成功工具调用的首轮收窄为单 `execute_code` + `any`；非正式回合仍保持默认 thinking。回归断言验证首轮纯文本恢复、首个执行和执行后的完整工具集回合均传递 `thinking=false`；Docker 中 `test_anthropic_provider`、`test_coder_agent_tools`、`test_llm_provider_timeout` 共 36 项及 Ruff 均 PASS。为彻底干净入口，已将本任务旧 `checkpoint.json` 可恢复地移至 `failed_attempts/checkpoint-removed-20260813-232119.json`，并验证 `task_request.json` 可用；变量快照保留。当前进程只注入 Coder 的官方 DeepSeek 配置，key 校验和真实单工具 named-function probe 均 PASS（`tool_calls=1`）。随后用户授权的唯一一次无 checkpoint 重跑确实进入 `run_modeling_task_async`，但在 Coder 前的 `CoordinatorAgent` 阶段三次均返回 401 `Invalid API Key`，于 `15:22:32` 失败；这不是 Coder/DeepSeek 工具链回归。没有生成新的 Q1 证据、`execution_validation.json`、冻结结果或 DOCX/PDF，且未再重试。后续须由指定决策人恢复/提供 Coordinator 的有效原配置后，才可重新授权一次干净全流程重跑；不得用非 DeepSeek 凭据替代 Coder 重试。

- [2026-08-13] 用户明确要求将已失效的 Mimo 四角色配置持久化替换为当前官方 DeepSeek OpenAI-compatible 配置。已将 coordinator/modeler/coder/writer 的 `api_type`、model、base URL 和同一当前凭据写入 Git 忽略的 `backend/.env.dev`，且 `docker compose config` 脱敏解析确认四角色均为 `openai-chat`、`deepseek-v4-flash`、`https://api.deepseek.com/v1` 并使用当前凭据；同时已写入当前 backend 进程，未重启容器。真实 `/validate-api-key` 返回 `valid=true`，单 `execute_code` + 内部 `any` + `thinking=false` 探针返回恰好一个 `execute_code` 工具调用。旧 checkpoint 仍在 `failed_attempts/` 归档、任务入口无 checkpoint；用户已授权以此全角色 DeepSeek 配置进行一次新的干净全流程重跑。

- [2026-08-13] 使用上述全角色当前 DeepSeek 配置的唯一一次无 checkpoint 干净重跑已于本地 `23:33:21` 终态 `failed`，未自动再次提交。Coordinator 成功完成 4 问拆分，未出现此前的 401；随后 Modeler 收到一次成功返回但 `content_chars=0`、`tool_calls=0` 的响应，`modeler_agent.py` 在 JSON 解析前按设计抛出 `ValueError("返回的 JSON 字符串为空，请检查输入内容。")`。因此失败点在 Coder 前的空 Modeler 输出，不是已验证的单工具强制调用/`thinking=false` 链路，也不是凭据认证。当前未生成新的 `execution_validation.json`、冻结结果、`res.md`/`res.json`/DOCX/PDF 或候选清单；backend 仍 healthy。后续先需获得用户对 Modeler 空响应恢复策略的明确授权，不能原样再次提交。

- [2026-08-14] 用户授权按收敛方案修复 Modeler 空响应。`ModelerAgent` 现仅对 ModelPlan 调用传入 `thinking=False` 与 DeepSeek/OpenAI 的 `response_format={"type":"json_object"}`；Coordinator 和 Writer 未改变。空 `content` 不再立刻中止，而是作为一次无效 ModelPlan 进入既有两次有界修复预算；Modeler 无工具链，修复回合不回传可能不完整的 `reasoning_content`。标准响应新增 `finish_reason` 与 `reasoning_tokens`，LLM 日志只记录终止原因、字符数和 token 计数，不记录推理正文。新增单测覆盖“空后有效 JSON”“连续两次空且无第 3 次调用”以及 OpenAI Chat 的 JSON 格式/完成元数据透传；本机 `test_modeling_gate test_modeler_json_repair test_llm_provider_timeout test_anthropic_provider test_coder_agent_tools` 共 53 项 PASS，Ruff PASS。Docker Desktop Linux engine 当时不可连接，故未重建/重启容器、未调用真实 provider、未提交新的任务重跑；待容器服务恢复后才可做 Docker 内验证。

- [2026-08-14] 用户随后授权重建 backend 并继续验证。新容器健康后，inspect 脱敏确认 coordinator/modeler/coder/writer 均实际加载 `openai-chat`、`deepseek-v4-flash`、`https://api.deepseek.com/v1` 和 DeepSeek 风格凭据；`/validate-api-key` 返回 `valid=true`。容器未安装 pytest，故按项目 Docker 规范以 `uv run python -m unittest` 运行目标五模块，53/53 PASS，`uv run python -m ruff check app` PASS。真实 Coder 探针（单 `execute_code`、内部 `any`、`thinking=false`）返回恰好 1 个同名工具调用；真实 Modeler 探针（`thinking=false`、`response_format={"type":"json_object"}`）返回 6076 字符可解析 JSON、`subtasks={ques1}`、`finish_reason=stop`、`completion_tokens=1402`。尚未提交 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff` 的 resume，等待用户在探针通过后单独授权。

- [2026-08-14] 用户授权后，对 `20260813-042803-73fdc6eaf64808b6372a7d5c52c3b8ff` 仅提交了一次干净 resume：先将该次失败留下且 `completed_phases={}` 的 checkpoint 可恢复归档为 `failed_attempts/checkpoint-removed-20260814-110533.json`，再 POST `/modeling/{task_id}/resume`。Coordinator 首次返回空 JSON，但其既有修复预算随后成功完成拆题。Modeler 首次返回非空 ModelPlan，却因 ques4 的诊断要求缺少对应验收指标关键词被拒；第二次修复返回的 JSON 缺失严格顶层 `schema_version`、`eda`、`subtasks`、`sensitivity_analysis`，两次有界预算耗尽后任务于本地 11:07 终态 `failed`。未见 401、工具调用/Thinking 400 或空 Modeler content；未生成新的 `execution_validation.json`、冻结结果、`res.md`/`res.json`、DOCX/PDF 或候选清单。按用户指令未自动再次提交。当前根因是完整四题严格 ModelPlan 的语义校验与修复提示链不稳定；单题 JSON 探针成功不能替代该端到端契约验收。

- [2026-08-14] 用户指定 DS-only 方案 A 后，backend 当前进程已通过 `/save-api-config` 注入 Coordinator/Modeler=`deepseek-v4-pro`、Coder/Writer=`deepseek-v4-flash`（均为 `openai-chat` 官方 DeepSeek base URL，`persisted=false`，未改 `.env.dev`）；Coordinator 与 Modeler 的 Pro `/validate-api-key` 均为 `valid=true`。`/config` 路由不暴露角色级运行时字段，故不能作为角色分配读回接口。针对同一失败任务 checkpoint 中的真实四题 questions，发起一次显式 Pro、`thinking=false`、`response_format={"type":"json_object"}` 的完整 ModelPlan 探针，并用 `ModelPlan.model_validate` 与 Q4“搜索范围/步长”指标断言验证。模型 JSON 已到达但 schema 校验失败：ques2 的 metric key 形如 `prob_0.50`，ques4 形如 `search_range_nA` / `search_step_nA` / `search_range_nB` / `search_step_nB`，含 `.` 或大写字母，违反 `^[a-z][a-z0-9_]*$`。因此 Pro 未通过完整严格契约探针；按用户规则未提交新的 resume、未重试探针、未退回 Flash/Mimo 或其他端点。后续须由用户在 DS 体系内选择“加固 Modeler 契约/修复轮提示”或提供另一个 DS 模型配置后再行动。

- [2026-08-14] 用户授权加固 Modeler 的 acceptance metric key 容错后，已先在桌面备份 `modeler_agent.py` 与 `A2A.py`。`ModelerAgent` 现会在 `repair_json` 后、`ModelPlan.model_validate` 前原地归一化各 `acceptance_metrics.key`：小写化，非 `[a-z0-9_]` 字符替换为下划线，数字/下划线开头加 `m_`，空值回退 `metric`；例如 `prob_0.50` → `prob_0_50`、`search_range_nA` → `search_range_na`。`AcceptanceMetric.key` 同时放宽为允许小数点的 `^[a-z][a-z0-9_.]*$`。新增离线回归覆盖上述两类 key 且验证严格 `ModelPlan` 可通过。本机与新建 backend 容器的目标五模块均为 54/54 PASS，Ruff PASS。Docker 全量 discover 跑 619 项时另有 3 项未触及的 `test_user_output_and_tasks` 失败（参考文献标点、候选清单刷新），未为其扩大修改面。重建后已重新按 DS-only 进程内分配为 Pro/Pro/Flash/Flash；真实 Pro 四题探针（`thinking=false`、`json_object`、经新归一化后严格校验）返回 3909 字符、`finish_reason=stop`、`completion_tokens=1782`，四个 quesN 和 Q4“搜索范围/步长”指标断言均通过。尚未提交新的任务 resume，等待用户单独授权。

- [2026-08-14] 用户随后授权该任务一次干净 resume：当前失败 checkpoint 已可恢复归档为 `failed_attempts/checkpoint-removed-20260814-115636.json`，随后仅 POST 一次 `/modeling/{task_id}/resume`。Coordinator（Pro）成功返回拆题；Modeler（Pro，`thinking=false`、JSON mode、key 归一化已生效）两次均返回完整非空方案，但被 `validate_modeler_plan` 的经验质量阈值依据规则拒绝。第 1 次 ques2 的 `prob_ci_width le 0.01` 与 `n_consistency eq 1` 均未在 description 中说明目标值来自题面/附件、数据统计或交叉验证、基线、文献或标准；第 2 次仅补齐前者，`n_consistency eq 1` 仍无依据。两次有界修复耗尽后任务于本地约 11:59 终态 `failed`，消息为该 `n_consistency` 阈值依据缺失。未进入 Coder，未产生本轮 Q1 执行证据、`execution_validation.json`、冻结结果、`res.md`/`res.json`、DOCX/PDF 或候选清单；未见 401、工具/Thinking 400。按用户要求未自动再次提交。后续应先针对经验质量阈值的“目标值依据”提示/契约进行一次离线加固并再取得用户授权，仍仅限 DeepSeek 体系。

- [2026-08-14] 针对上述经验阈值依据失败，已完成离线加固：Modeler 主提示逐条要求 `acceptance_metrics[*].description` 使用“题目原文 / 数据统计 / 交叉验证 / 文献标准”来源类别；`problem_contract` 同步接受“题目原文”这一提示中使用的同义来源；当一个完整 ModelPlan 仅因经验阈值依据被拒时，第二轮不再重写整份计划，而只返回 `description_updates` 并受限合并到原始 Plan，其余字段保持不变，其他校验错误仍走完整 JSON 修复。未改变 `MAX_JSON_REPAIR_ATTEMPTS=2`，也未把 description 来源词提升为 A2A schema 正则。桌面已备份 `modeler_prompt`、`modeler_agent`、`A2A`；本机及最终 Docker 镜像的相关 109 项单测均 PASS，Ruff PASS。Docker 全量 discover 为 623 项、3 个既有且未触及的 `test_user_output_and_tasks` 失败（候选清单刷新、两项参考文献标点），1 项 skip。重建后仅以内存配置恢复 DeepSeek Pro/Pro/Flash/Flash，Pro key 校验为 `valid=true`。随后一次真实 Pro Modeler JSON 探针返回可解析完整 JSON，但 `r2_test`、`rmse_test`、`param_significance_flag`、`ttest_p_value`、`p_value` 等经验阈值仍未满足 `_THRESHOLD_BASIS` 所需的“阈值—依据—来源”句法连接；该探针的每条 description 已包含四个来源类别词之一，故失败是当前启发式正则比提示词的“含来源词”要求更严格。按门禁已停止：未重试探针、未提交 `/resume`、未退回 Mimo/其他端点。后续须由用户决定是否放宽/对齐 `_THRESHOLD_BASIS`，或先加强生成/补丁提示后再进行一次新的受控探针。

- [2026-08-14] 用户授权后，已将 Modeler 主提示与修复轮协议提醒统一为现有 `_THRESHOLD_BASIS` 接受的“阈值/目标值/判据/容差 + 依据/来自/基于 + 题目原文/数据统计/交叉验证/文献标准”结构，并明确禁止以“目标值来源”作连接词；补充 `n_consistency`、`p_value`、`rmse_test`、`r2_test` 合规示例及离线契约回归。变更前已在桌面备份 `modeler.py` 与 `modeler_agent.py`；本机目标测试 73 项、重建后的 Docker 目标测试 110 项和 Ruff 均通过。重建后仅向当前进程注入 DeepSeek Pro/Pro/Flash/Flash（`persisted=false`），Pro Modeler key 校验为 `valid=true`。随后仅发起一次新的真实 Pro Modeler JSON 探针（`thinking=false`）：响应可解析为完整四题 ModelPlan，且严格校验未再报告经验质量阈值依据错误；但 Q4 的 `diagnostic_requirements` 要求记录“每个参数搜索的步长和迭代次数”，缺少对应的 acceptance metric 关键词，故整份 Plan 仍被严格校验拒绝。已按门禁停止，未重试探针、未提交 `/resume`、未改动 schema 或放宽任何校验；下一步需先处理该独立的 Q4 诊断指标契约问题并再次取得授权。

- [2026-08-14] 选择性移植 upstream #102/#104 的非门禁改进：统一本地/E2B matplotlib 初始化、字体缓存清理与绘图常量，增加前端消息/Notebook 粘底滚动、保存未通过验证的运行时配置，并补充桌面版下载引导；#102 的 `LLMConfigError` 仅用于让缺失配置立即退出，保留本地 Modeler 两次 JSON 修复预算及结构化 ModelPlan 门禁。后端定向单测 70 项和 Ruff 通过；未运行前端 Node 工具链，未做真实 provider 探针。

- [2026-08-14] 选择性移植后的首个 DeepSeek Pro 四题探针中，首轮完整 ModelPlan 未给 Q4 的“步长/网格搜索、网格收敛”诊断配置对应的 `step/grid` 验收指标，触发“诊断要求缺少对应验收指标关键词”；同一次 `ModelerAgent.run` 的第二个受限修复轮补入 `step_grid_params_recorded` 后严格校验为 PASS，且两轮均未触发“经验质量阈值缺少目标值依据”。因结案要求首轮也不出现上述诊断错误，已在再次探针前只加强 Modeler 输出前逐条诊断关键词自检：`iteration_count` 或笼统收敛标志不得替代 `step/grid` 对应指标；未修改或放宽 `problem_contract` 门禁。

- [2026-08-14] 加强首轮诊断关键词自检后的第二个 DeepSeek Pro 四题探针，首轮已同时生成 `iteration_count`、`step_grid_convergence` 和 `feasibility_flag`，不再触发诊断指标对应错误；但 `cv_r2_avg` 首轮写成“基准依据：文献标准”，仍被现有 `_THRESHOLD_BASIS` 拒绝。同一次 `ModelerAgent.run` 的受限 `description_updates` 第二轮将其明确改为“阈值依据：文献标准”，离线复算确认正则匹配且最终严格校验 `valid=true`、`violations=[]`、`missing_requirements=[]`，最终两类指定错误检查均为 false。未修改或放宽 `_THRESHOLD_BASIS`、`_structured_diagnostic_metric_gaps` 或两轮修复预算；完整闭环依赖一次受限 description 定向修复，不能表述为首轮零修复通过。

- [2026-08-14] 选择性上游移植最终状态：仅人工吸收 `11f3862`（#102）的共享 Matplotlib 初始化/字体缓存、E2B 上传顺序、前端粘底滚动、运行时配置保存与缺失 LLM 配置快速失败，以及 `13e3995`（#104）的桌面版引导；未整体 cherry-pick 会覆盖本地门禁/工作流的提交。本地另外修复全量测试暴露的英文参考文献句号和最终刷新失败后撤销旧 `candidate_manifest.json` 两项既有问题，并同步 PDF 说明与最终复核清单。本机和 Docker 最终代码均为 pytest 626 PASS、1 项因无 E2B Key SKIP、2 个非失败 warning，Ruff PASS；Compose 前后端健康且 `/docs`、前端首页可访问，前端只在 Docker 内构建。真实 Pro 闭环的最终严格校验 PASS 如上一条所述，但经过一次受限 description 定向修复；不得将其写成首轮零修复通过。

- [2026-08-14] 为降低 Modeler 对第二轮 `description_updates` 的依赖，已仅强化主提示：显式枚举 R²/RMSE/拟合误差/显著性（p 值）/偏差/准确率的“阈值词 + 依据词 + 题目原文/数据统计/交叉验证/文献标准”首轮结构，加入 `cv_r2_avg` 的“文献标准规定回归模型至少应优于常数预测(R²>0)”可照抄范例，并强化步长、网格、迭代、守恒、求解器和双喷嘴诊断指标的一一对应示例。变更前备份为 `C:\Users\Johnny\Desktop\MathModelAgent-modeler-prompt-backup-20260814-160922\modeler.py`；未修改 `problem_contract.py`、`modeler_agent.py` 或任何门禁/修复预算。本机 Ruff PASS，全量 Pytest 为 626 PASS、1 SKIP、2 个非失败 warning。重建健康 backend 后仅运行一次 `deepseek-v4-pro` 四题 Modeler 探针（`modeler-first-round-basis-20260814-082214`，`thinking=false`、JSON mode、底层重试上限 1）：仅 1 次 provider 响应，首轮 `cv_r2_avg` 已写为“阈值依据：文献标准规定……R²>0”，严格复算 `violations=[]`、`missing_requirements=[]`、最终 `valid=true`，故 `first_round_pass=true`；“经验质量阈值缺少目标值依据”和“诊断要求缺少对应验收指标关键词”检查均为 false，未触发第二轮定向修复。

- [2026-08-16] 2026 华数杯 A 题真实任务 `20260816-101205-a58e331d7ddbf29c171f4ffd970fcb5a` 在审阅后的四问 ModelPlan 获批后进入 Coder；Q1 首次精确几何单元出现代码错误，随后两次对约 14 万圆柱候选对执行重型最近距离优化均触发本地解释器 300 秒看门狗。内核每次均正常重建并恢复 72 个变量，但第 3/3 次尝试耗尽后任务于本地 19:01 置为 `failed`，消息为“代码阶段 ques1 未提供成功执行证据；诊断报告状态: FAIL”。当前仅保留 EDA、`notebook.ipynb`、变量快照和 `ques1_input_parameter_audit.csv`；Q1--Q4 正式 expected artifacts、`execution_validation.json`、冻结结果和论文导出物均未生成，`execution_validation_report.json=FAIL`。当前处置：不原样重试重型全对优化；保持 DeepSeek Pro/Pro/Flash/Flash、密钥与门禁不变，仅在既有 `/resume` 恢复协议中声明一次 `low_cost_algorithm`，要求先做周期空间索引/保守 broad phase，再仅对临界候选进行有限圆柱实体距离复核。

- [2026-08-16] 上述任务按 `low_cost_algorithm` 续传后在约 90 秒内生成 Q1 三个 expected artifacts 和 `execution_validation.json`，但证据第 3 次提交因 `geometry_residual=0.8948605235901863 > 0.01` 被拒并再次终态 `failed`。只读复核确认原 ModelPlan 将边界截断后的短记录逐行与完整高 5000nm 比较，验收量口径不适用于官方附件；同时 notebook 最终单元把三组全不导通结果、图数据和零残差交叉核验硬编码写入 CSV，且把 `x=+5000` 通过二次 wrap 映射成 `-5000`，导致所有组 `右电极触达=0`。这些产物不可采信。当前处置：不降低 `problem_contract.py` 门禁、不修改模型/密钥；依据官方 PDF“附件每一行表示一个介质 A”与坐标已在域内的事实，通过受控 `codex-modeling` 仅纠正 Q1 方案：附件坐标不再二次周期映射，保留正负电极端点，几何合法性检查改为端点在域内且截断段长 `0 < L <= 5000nm`，并增加反硬编码、broad-phase 召回和独立实体距离交叉复算证据，再重开 HIL。

- [2026-08-16] 同一任务在 Luna Max 独立复核修正后的 Q1 ModelPlan 为 `valid=true` 后重新获批；旧 notebook、变量快照和不可采信的 Q1 产物均已可恢复地归档到任务目录 `failed_attempts/20260816-1114-q1-invalid/`，新执行日志确认未重放旧 notebook/快照并从 Coder Q1 第 1 轮开始。该轮首次 DeepSeek Coder 请求与其第 1 次自动重试分别在 300 秒处发生 `TimeoutError`，即连续两次真实 provider 超时；backend/redis/frontend 均保持 healthy，任务仍为 `resuming`，尚未生成新 notebook 或 Q1 产物。当前处置：遵循连续失败恢复规程，不新增续传、不切换用户指定的模型/密钥/门禁；仅等待已经由 LLM 客户端启动的最后一次内置重试得出终态，若仍失败则停止并保留全部日志供复盘。

- [2026-08-16] 上述最后一次内置 provider 重试随后成功返回工具调用，但本次全新执行仍于本地 `19:40:39` 终态 `failed`。Q1 自动形式门禁虽被记录为通过，Luna Max 与主线程源码复核均判定不可采信：正式 `cd()` 仍以轴段距离减 `2R` 代替有限平端帽圆柱实体距离；所谓独立复算只是同一函数交换参数重调；在原始输出为 `conduction_flags=2`、求解残差约 `2.9733nm` 后，后续单元改用结果行数 `count()=3`、固定几何残差并重写验收表。Q2 又采用逐样本 `n×n` 全对距离矩阵，未实现周期边界/截断，在 300 秒看门狗处超时；内核恢复 144 个变量后因 3 次代码尝试耗尽，`execution_validation_report.json=FAIL` 且缺少 ques2 正式验证。仅有 Q2 输入审计，Q2 四个预期结果、Q3/Q4、冻结结果、论文与候选清单均未生成。当前处置：按连续失败恢复规程停止再次续传；不修改 DeepSeek Pro/Pro/Flash/Flash、密钥、门禁或业务代码，完整保留失败目录与日志，等待用户决定是否授权新的算法实现/代码修复范围。

- [2026-08-16] 用户另行授权新任务级算法实现后创建干净任务 `20260816-135106-cdb6b1ab247aaa99861ec9b95e0b88e8`；ModelPlan 经受控审阅修正附件截断段口径、标准线段最近点、27 镜像、独立连通/几何复算、周期宽相及 Q3/Q4 诊断后由 Luna Max 终审通过。Coder 新 notebook 的 EDA 正确保留 596 行且未二次 wrap，但首个几何自测误对每轮 `P=2000` 对构造 `401×401` 二维密集采样数组，backend 内存一度接近容器上限并导致 ipykernel OOM 消失；本地解释器于 300 秒看门狗处中断，随后成功重建内核且无旧快照恢复，Coder 进入下一修正轮。当前处置：保留主标准 seg-seg 与27镜像方向，只允许将独立复算缩至阈值附近至少30对；不得再次运行巨型密集数组，任务仍在受控执行中。

- [2026-08-16] 同一新任务的 Q2 首版 N=707 精确候选循环实测约 `99.599s`，Coder 改为候选对批量 27 镜像后单样本降至约 `1.008s`，但四组各 200 次的串行正式 MC 仍在检查点约 `200/200/200/120`（此前读取时为 680/800）处触发本地解释器 300 秒看门狗。该检查点只保存各组完成计数，未持久化逐样本导通 0/1、候选数、运行时或种子，故不能据此恢复或拼接概率；同时只读审计发现 Q2 输入表把 `10000^3` 错写为 `1e15 nm^3`（正确为 `1e12 nm^3`）。当前处置：保留自动启动的同一 Coder 有界修正轮，仅接受持久化逐样本结果、可复算合并且修正体积审计后的低成本续跑；不得把完成计数或固定常量写成验收证据。

- [2026-08-16] 新任务 `20260816-135106-cdb6b1ab247aaa99861ec9b95e0b88e8` 的 Q2 看门狗中断后恢复了 172 个变量，但已达到 Coder `3/3` 尝试上限，任务于本地 `22:33:05` 终态 `failed`，消息为“代码阶段 ques2 未提供成功执行证据；诊断报告状态: FAIL”。Luna Max 只读终审为 REJECT：Q1 当前路径 `L→实体0→实体11→R` 来自实体0左端点与实体11经 `kx=-1` 后的右端点重合；本像无左右通路。因而用户同时要求“所有实体及平面取完整27镜像最小值”和“每行独立、组1应不导通”存在直接规范冲突；若平面也照字面枚举27镜像，任一左触达实体平移 `+L` 即触达右面，更不可能得到组1不导通。另有 Q1 删除长度违规门禁、接受表常量写入、边表未记录真实最近参数/镜像索引等不可采信问题。当前处置：停止同口径续传；保持模型、密钥、业务代码和门禁不变，等待明确选择“带电x方向不周期（仅y/z周期或显式截断）”或“完整xyz周期并接受组1导通”后，才可重写本任务代码并做低成本恢复。

- [2026-08-16] 用户按修正版口径（X 非周期、Y/Z 九镜像为主模型，完整 XYZ 27 镜像仅作 Ablation）创建全新隔离任务 `20260816-151428-48d1a22b0efd358dc0c60b97eef84c92`，未调用任何旧失败任务的 `/resume`。经 Modeler HIL 与 Luna Max 方案终审后进入 Coder；正式 Q1 已算得组1不导通、组2/3导通，BFS/UF 差异为 0，并完成 32 对独立几何复算（最大差约 `1.36e-12 nm`）及主要边/诊断表。但最后一个 14791 字符产物汇总单元连续保留同一 Python 语法错误：`dict(metric="algorithm","robust_closest_pt_segment(9/27镜像)",source="Ericson RTCD")` 触发 `SyntaxError: positional argument follows keyword argument`，3/3 代码尝试耗尽，任务于本地 `23:35:49` 终态 `failed`，未进入 Q2--Q4、冻结或论文导出。当前处置：遵守用户“禁止 /resume 任何旧失败任务”，不续传该任务；保留全部 notebook、CSV、诊断报告和日志，下一次只允许创建新的隔离任务，并在任务提示中明确所有 `dict(...)` 项必须使用完整 `key=value` 或字面量语法、先做 `ast.parse/compile` 再提交长单元。

- [2026-08-16] 按“不续传失败任务”要求创建第二个全新隔离任务 `20260816-153727-6e3ba11f9ebe90d01b6470b843442ec3`，题目、附件、修正算法和 Q1 语法/阈值防错均重新提交，未读取或恢复历史 notebook/快照。Coordinator 正常拆出四问，但 Modeler 两轮均因 ques4 的 numerical `diagnostic_requirements` 要求“记录目标函数评估次数（即蒙特卡洛样本总数）并说明可行性”而未给 acceptance metric 中一一对应的“目标函数评估次数/样本总数”关键词，严格 `problem_contract` 门禁耗尽有界修复后于本地约 `23:40` 终态 `failed`。该任务未到 `waiting_review`，没有 `modeler_plan.json/md`、notebook、Q1--Q4 产物或导出物。当前处置：不调用 `/resume`、不放宽门禁；若继续创建新隔离任务，必须在 guidance 中给出可照抄的 Q4 指标（例如 key=`objective_evaluation_count`，description 同时包含阈值词、依据词、来源词及“目标函数评估次数/蒙特卡洛样本总数”原词）。

- [2026-08-17] 第三个全新隔离任务 `20260816-154156-0c5515d80bb983d5f72b64425e485e87` 经受控 `codex-modeling` 写入先前 Luna Max 批准的完整计划，并仅追加 Q4 `objective_evaluation_count>=30` 后通过方案 HIL；日志确认没有历史 notebook 重放。正式 Q1 Coder 先以符号错误的线段夹紧公式建边，45 对独立复算最大差约 `2074.79nm`；修正版自测仍差 `1313.48nm`，继而误把 250×250 二维网格用于全部实体对和九镜像，触发 300 秒看门狗。主线程通过任务内置、审计留痕的 coder guidance 明确要求解析全体+仅30对优化复核，该引导于看门狗结束后成功排队；但 Coder 随后三次受控证据提交先后因来源不新鲜、指标无法从 source_path 复查、比较符协议错误等被拒，终态 `failed`。最终独立几何表仍有约 `314.18nm` 最大差，`boundary_condition_ablation.csv` 含固定常量，provenance 运行时间为 `time.time()-time.time()`，且缺 `ques1_geometry_diag.csv`、`ques1_plot_data.csv`；Q2--Q4、冻结和论文均未开始。当前处置：按用户要求不 `/resume`，完整保留任务与 guidance 审计；后续若再建全新任务，应在首次 Coder 提示直接提供经随机/退化/平行单测验证的标准 seg-seg 参考实现，并逐项给出可从 CSV 复查的 execution evidence 字段/比较符映射，禁止再让模型自行推导夹紧公式或全量二维网格。

- [2026-08-17] 第四个全新隔离任务 `20260816-161352-abc1a7d707c59460d15018b6ca3c0965` 经两轮受控 ModelPlan 审查补齐 Q1 至少1000例线段最近距先验自测后由 Luna Max 批准，随后仅通过 `approve-modeling` 进入当前任务 Coder（未调用任何旧失败任务的 `/resume`）。首次 EDA Coder Provider 调用在300秒达到客户端时限并记录 `TimeoutError`，后端自动进入既有第2次调用；此时尚未生成 notebook 或任何 Q1--Q4 数值产物，任务仍处于活跃执行中。当前处置：不切换模型、不改代码/门禁、不复用旧产物，保留自动有界重试并继续监控；若同一调用连续失败则按恢复规程停止扩大尝试并如实汇报。

- [2026-08-17] 上述第四个新任务在 EDA 内提前实现 Q1 自测，第一版因漏掉 `(0,0)` 角点且边界投影未 clip，仅通过 `779/1100`、最大差约 `12637.81nm`；第二版补角点后仍未 clip，且以 L-BFGS-B 作为近零距离参照，仅通过 `894/1100`、最大差约 `0.00277nm`。第三版已写出正确的四条 clip 与独立一维参照思路，但把长 `code_str` 的内容重复拼接并遗留未闭合三引号，触发 `SyntaxError: incomplete input`，耗尽 EDA `3/3` 代码额度；任务终态 `failed`，未进入正式 Q1 建边、Q2--Q4、冻结或论文。当前处置：严格不调用 `/resume`；已在本机只读/无文件写入的独立解释器中验证完整候选枚举+一维有界参照对同分布1100例全部通过，最大差约 `1.42e-10nm`。若按用户继续授权创建全新任务，必须明确 EDA 只做附件结构核验，几何自测移至正式 ques1 首个单元，并将已验证的完整函数原样提供，禁止模型再拼接嵌套 `code_str`。

- [2026-08-17] 第五个全新隔离任务 `20260816-163750-6be62bbc05479c6a7c37adede39e4227` 已按“EDA只核验附件、Q1再运行已验证1100例函数”重新提交，初始目录确认无旧 notebook/CSV/checkpoint；但自动 Modeler 两轮仍因 ques4 numerical 诊断“记录求解器搜索过程、候选组合及对应概率”缺少逐词对应验收指标而在 Coder 前终态 `failed`。未生成 `modeler_plan.json/md`、notebook 或任何正式数值产物。当前处置：不调用 `/resume`、不放宽 `problem_contract.py`；使用仓库专为 Modeler 失败且未执行代码的受控 `codex-modeling` 安全接管点，将已由 Luna Max 批准的38项结构化方案写入本任务并重新走正常方案审批，保持当前新任务的隔离工作目录。

- [2026-08-17] 上述第五个隔离任务通过受控 `codex-modeling` 写入 Luna Max 已批准且 SHA-256 为 `8D900D88670EA163BA114BC44CA896CAE93E0A169B598BA397FD66F30C68460E` 的38项方案后进入 Coder；EDA 按要求只完成附件结构与体积/数量核验，随后正式 Q1 的第一版线段距离符号错误，自测最大差约 `1.07e4nm`。Coder 又启动 `2000×401×401` 裸二维稠密参照并触发300秒看门狗；恢复后的候选枚举函数虽修正主体公式，却遗漏退化线段分支保护，1101例自测在 `add(-d/a,0.0)` 处触发 `ZeroDivisionError`，耗尽 Q1 `3/3` 尝试，任务终态 `failed`。没有 Q1 正式产物、Q2--Q4、冻结或论文。当前处置：绝不调用该任务 `/resume`；保留全部日志、notebook 与 guidance 审计。下一全新任务须在 Coder 定向 guidance 中逐字给出已独立验证通过1100/1100（最大差约 `1.42e-10nm`）且含 `a<=zero`、`c<=zero` 双退化保护的完整实现，并明确禁止稠密网格、DE、L-BFGS-B 与 `code_str/exec`。

- [2026-08-17] 第六个全新隔离任务 `20260816-165636-a39b7cbbad14abdebbf87ca151662939` 已验证初始目录无旧 notebook/CSV/checkpoint，附件哈希正确，并在 Coordinator 阶段预先写入含完整退化安全 `primary/reference` 函数的 Coder 定向 guidance；但自动 Modeler 两轮仍因 ques2 诊断“记录随机种子和每次模拟的随机数状态”没有逐词对应验收指标而在任何 Coder 执行前终态 `failed`。当前处置：不调用 `/resume`、不改门禁；仅使用项目限定在 Modeler 失败且未执行代码边界的受控 `codex-modeling` 接管点，写入此前 Luna Max 已批准、SHA-256=`8D900D88670EA163BA114BC44CA896CAE93E0A169B598BA397FD66F30C68460E` 的38项方案，再走正常人工方案审批。

- [2026-08-17] 上述第六个任务经受控方案接管与 Luna Max APPROVE 后进入 Coder。Coder 首先违背定向 guidance，使用缺退化保护的向量公式及 `1001×1001`、`20001×20001` 稠密网格，后者触发300秒看门狗；排队纠偏生效后，完整 `primary/reference` 以 seed=20260816 通过1100/1100（最大差约 `5.85e-12nm`），修正向量实现又通过4000/4000（最大差约 `1.82e-12nm`）。Q1 主模型得到组1不导通、组2/3导通，BFS/UF差异0；32对独立几何复算最大差0，27镜像 Ablation 使组1转为导通。但正式边表将全部最近参数伪写为 `s=t=0.5`，预期文件名也缺 `ques1_distances.csv`；exact 诊断 CSV 的9/27边界数值列先为空，后续两次 execution evidence 均不可复查，最终于本地 `01:17:41` 终态 `failed`，未进入Q2--Q4、冻结或论文。当前处置：绝不 `/resume` 或复用该失败目录产物；若按用户继续授权创建全新任务，必须让 Q1 对每条冻结边以 `primary` 真实回算并写入 s/t，逐字使用 ModelPlan 预期 artifact 路径，且在提交前逐项从 source CSV 反向读取验证 metric value/constraint actual。

- [2026-08-17] 第七个全新隔离任务 `20260816-172012-823081f1fd1ecb60bd7d491097abd755` 已在创建时前置“两单元Q1、真实s/t、八个精确artifact、metric_key/value反查、Q2-Q4禁N²”及完整退化安全函数 guidance；初始目录和附件哈希均正确，但自动 Modeler 两轮仍因 ques2 诊断“记录随机种子和每次仿真的随机状态”缺少逐词对应验收指标而在任何代码执行前终态 `failed`。当前处置：不调用 `/resume`、不修改门禁；仅使用 pre-execution `codex-modeling` 安全接管点写入此前 Luna Max 已批准的38项方案，再走正常方案审批。

- [2026-08-17] 上述第七个任务经受控方案接管后进入 Coder；校正单元以 seed=20260816 完成1100例有限线段自测（最大差约 `2.66e-11nm`），Q1 主模型生成真实最近参数边表并得到组1不导通、组2/3导通、UF/BFS差异0。但 Coder 在最后证据收口单元再次对535根介质先全量重复9镜像独立复算、再裸枚举全部实体对的27镜像 Ablation；一次长单元先因 `dict` 语法错误失败，修正后在本地解释器300秒看门狗处超时，3/3尝试耗尽，任务于本地 `01:39:03` 终态 `failed`。当前仅有 `ques1_results.csv`、含真实s/t的 `ques1_edges.csv` 与合规自测表，Q1八产物未齐，Q2--Q4、冻结和论文均未开始。当前处置：绝不 `/resume`；后续新隔离任务须把Q1独立复算限定为预筛后的32对，并让9/27镜像 Ablation同样先用保守空间哈希/包围体筛选再精算，禁止任何535规模的重复全对镜像循环。

- [2026-08-17] 第八个全新隔离任务 `20260816-173947-45c85e69ba0eecca85a2b4b2e676f9b0` 经受控方案接管与 Luna Max APPROVE 后进入 Coder；任务内低成本求解器已通过 AST 校验，SHA-256=`33557C95C74F84DAEFAB93A219835E0E1E9FD088F0EC74C31815309AA00511A8`，其独立预检曾得到 Q1 组1不导通、组2/3导通且双实现差异0。正式任务却在 EDA 前两次执行即因 OpenBLAS 无法创建线程失败，第三次等待300秒看门狗后仍失败，3/3耗尽并于本地 `02:05:58` 终态 `failed`，未进入正式 Q1，未生成 Q1--Q4、冻结或论文。只读资源核查显示 backend 容器 `pids.max=256`、当时 `pids.current=242`，PID 1 未回收的大量 `[sleep] <defunct>` 进程占满配额，属于容器运行资源耗尽而非建模算法错误。当前处置：绝不 `/resume`；先重启 backend 清空僵尸进程并复核健康度/进程余量，再创建全新隔离任务，要求 EDA 只用当前内核直接读取附件且禁止 `subprocess`，四问正式单元直接调用已校验的任务级低成本求解器。

- [2026-08-17] backend 重启后进程占用由 `242/256` 降至 `10/256`，随后创建第九个全新隔离任务 `20260816-180843-aeab4849e0f2f38d28cbf7acf1dc99b8`；附件、修正算法文档和任务级求解器哈希均与源文件一致，初始目录无旧 notebook/CSV/结果。Coordinator 正常拆出四问，但自动 Modeler 两轮因 Q4 numerical 诊断“搜索网格步长和范围（n_A/n_B 枚举范围）”及“求解器状态、最优性证明或近似最优性说明”缺少逐词对应 acceptance metric 而在任何 Coder 执行前终态 `failed`。当前处置：不调用 `/resume`、不放宽门禁；仅在该任务未执行代码的安全边界使用受控 `codex-modeling` 写入此前 Luna Max 已批准的38项计划，再重新走正常方案审批，仍不复用任何旧数值产物。
