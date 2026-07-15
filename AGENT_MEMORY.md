# AGENT_MEMORY

## 当前稳定状态

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
- 模型生成代码默认必须通过 E2B 远程沙箱执行（`CODE_INTERPRETER_KIND=remote`）。新增
  `auto` 模式：有 E2B 时优先远程沙箱；缺少 E2B 时仅在显式
  `ALLOW_LOCAL_CODE_EXECUTION=true` 的本地执行 Compose 覆盖文件中降级到 Jupyter。
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
    正文 30 页以内、物理边缘越界和 CUMCM 2.5cm 内容边距风险
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

- [2026-07-15] 合并后 Docker 真实轻量线性规划任务 `20260715-083558-bcf5af9ad14cac9627c3ad92b2a839db`：受控本地执行模式下 Coordinator、Modeler、Coder、变量快照、两问 CSV/图表、`execution_validation_report.json = PASS` 和 `frozen_results.json` 均实际完成；真实 Redis 经 `5173/ws` WebSocket 代理的探针消息也成功转发。但 Writer 后的 `paper_preflight_report.json = FAIL`，硬失败仅为 `result_consistency`（17 个冲突）和 `figure_result_consistency`（3 个冲突）：检查器把 LaTeX 计算式中的首个乘数（例如 `40 \times 40 + 30 \times 20 = 2200` 中的 `40`）误当成最终赋值，并在同类句子中混淆原最优利润 `2200` 与新最优利润 `2366.67`，属于预检数值抽取/指标作用域误报。任务正确终止为 `failed`，未生成 PDF/DOCX/最终验收报告；当前处置：不重跑 provider，保留 checkpoint、`res.md/res.json`、冻结和执行证据，修复前先为表达式末端结果与原/新指标作用域建立最小回归，之后仅走确定性重新预检/导出。
