# Agent 源码修复与最终验收计划

## 1. 目标与范围

本计划解决 WebUI 主工作流中“模型已执行但无法稳定形成可验收交付物”的问题。目标是让普通数学建模任务在不伪造数值、不绕过安全门禁的前提下，稳定完成：

1. 题面要求、固定参数和每个正式问题均被建模方案覆盖；
2. 每个正式问题均有真实代码执行、结构化结果和可复核来源；
3. 验证失败时只回修失败问题，而不是丢弃全部已通过结果；
4. Writer 仅使用冻结后的数值事实；
5. 自动生成技术验收报告，并明确标记仍需人工确认的项目；
6. 最终导出链路满足 `CUMCM_FINAL_REVIEW_CHECKLIST.md` 的技术前置条件。

本计划不把自动化报告视为数学正确性或竞赛合规的最终替代。人工复核模型假设、推导、数值收敛、引用真实性、正式字体和提交规则仍为必需步骤。

## 2. 已确认的问题

### 2.1 高压油管真实任务暴露的问题

任务 `20260713-094126-a94c9d8a07cce0aa80ea9cb844338b52` 的历史记录表明：

- 问题一曾只有 PNG，缺少可校验数值来源；问题二曾没有结果文件；
- 问题三曾使用上一问的估计值，且减压阀动作次数为零；后续虽有阀门动作，压力波动仍不满足稳定目标；
- 模型将 `subtasks` 错写为 `tasks`，并曾使用不符合约定的比较符、把 CSV 登记为图表；
- 原流程在最终执行验证和结果冻结前已让 Writer 开始写作；
- 本地数值实验出现高 CPU、无 IOPub 返回，旧超时机制无法及时中断。

当前工作区已新增题面契约、执行验证、结果冻结和 OS 级看门狗，能够阻断上述大量错误；但还缺少稳定的“失败诊断 → 局部修复 → 再验证”闭环。

### 2.2 当前架构中的根因

| 层级 | 根因 | 影响 |
| --- | --- | --- |
| Modeler | `ModelerToCoder` 仅传递自由文本字典；没有逐题可机读的交付契约与精确键覆盖校验。 | 方案可能遗漏问题、输出要求或可验证指标。 |
| Coder | 要求模型手工写完整 `execution_validation.json`、计算哈希并维护跨题 JSON。 | 容易出现字段、路径、哈希和图表来源的格式错误。 |
| Workflow | 执行验证失败后清空所有 solution checkpoint 并终止。 | 已通过问题被重复计算；模型没有收到具体失败项，人工续传成本高。 |
| Validation | 高压油管规则较完整，但通用题型的“题面要求 → 指标 → 证据”映射不足。 | 普通任务只能依赖提示词，无法稳定保证验收覆盖。 |
| Export/Audit | 附录 B 目前截取核心代码，submission audit 不检查完整代码是否实际进入论文附录。 | 自动 `PASS` 不能等价于最终提交可接受。 |
| Tests | 主流程验证大量使用 Mock，缺少一个覆盖真实产物契约的无 LLM 端到端 fixture。 | 单测通过不能证明普通任务的完整交付闭环。 |

## 3. 设计原则

1. **模型负责建模与计算，程序负责结构化证据和状态转换。** 不依赖模型手工维护跨问题的审核 JSON。
2. **先验证、再冻结、后写作、再导出。** 任何失败证据不得进入 Writer 或最终论文。
3. **局部重试。** 只重做未通过的 `quesN`；每个真实 provider 最多一次自动定向回修，连续两次失败按恢复规程停止。
4. **通用内核 + 领域 profile。** 共性验证进入通用 schema；高压油管等专项约束使用 profile，不把领域阈值误用于所有题目。
5. **报告分层。** 技术门禁、人工数学复核、正式提交复核分别报告，避免把 `PASS` 误表述为论文正确。
6. **安全边界不放宽。** E2B 继续是默认执行器；本地执行只限受控单用户 Docker 覆盖，超时仍按失败处理。

## 4. 分阶段实施方案

### 阶段 A：建立结构化建模计划契约

#### 改动

- 扩展 `backend/app/schemas/A2A.py`：以 `ModelPlan`、`SubtaskPlan`、`ExpectedArtifact`、`AcceptanceMetric` 替换自由文本的核心交接。
- 扩展 `backend/app/schemas/problem_contract.py`：
  - 记录正式问题键集合；
  - 对每题记录要求、输入来源、不可变参数、预期数值产物和验收条件；
  - 保留目前高压油管的确定性规则，但新增线性规划、数据驱动、一般仿真的通用 requirement builder。
- 修改 `backend/app/core/agents/modeler_agent.py` 与 `backend/app/core/prompts/modeler.py`：
  - 强制每个正式 `quesN` 输出完整计划；
  - 在返回前校验键集合精确匹配 Coordinator 拆题；
  - 对缺失、改写固定参数、缺少验收指标的计划进行最多两次 JSON 修复。
- 修改 `backend/app/core/flows.py`：把每题计划中的产物和验收条件传给 Coder，而不是仅传递自然语言方案。

#### 完成标准

- Modeler 无法返回缺失正式问题、未知问题键或无验收指标的计划；
- 线性规划 fixture 能表达目标、约束、最优解和敏感性分析；
- 高压油管 fixture 能表达指定过渡时刻、阀门控制和稳定性要求。

### 阶段 B：由后端生成执行证据

#### 改动

- 新建 `backend/app/tools/evidence_collector.py` 与对应 Pydantic schema：
  - Coder 只提交单题 `ResultEvidence`，包含结果 CSV/JSON 路径、指标定义、约束表达、图表原始数据路径；
  - 后端校验路径在当前任务目录内，读取有限数值，计算 SHA-256，生成标准化证据；
  - 后端汇总各题证据生成 `execution_validation.json`，禁止模型直接覆写其他问题证据。
- 修改 `backend/app/core/agents/coder_agent.py` 与 `backend/app/core/prompts/coder.py`：
  - 添加受控的 `record_result_evidence` 工具；
  - 代码执行成功不再等同于子题完成；只有工具提交证据成功才标记该题为可验证；
  - 执行输出只作为调试上下文，不能成为数值事实源。
- 重构 `backend/app/tools/execution_validation.py`：保留现有硬验证逻辑，输入改为后端收集的证据；专项规则以 profile 形式注册。

#### 完成标准

- 无论模型写出 `tasks`、`file`、PNG 来源或伪哈希，均无法形成有效执行清单；
- 每个通过的 `quesN` 都有任务内结构化数值来源与可复算 SHA-256；
- 高压油管的守恒残差、阀门扰动证据和压力稳定性继续保持硬门禁。

### 阶段 C：加入定向回修状态机

#### 改动

- 修改 `backend/app/core/workflow.py` 与 `backend/app/core/checkpoint.py`：
  - 将状态细分为 `solving`、`validating`、`repairing`、`frozen`、`writing`、`exporting`；
  - 验证失败时保存失败报告与失败 `quesN`，保留已通过题目的证据和 checkpoint；
  - 仅向 Coder 回传失败检查项、相关来源文件、时间/资源上限和明确修复动作；
  - 每个任务最多一次自动定向回修；第二次真实失败必须停止，写入失败记录并要求指定决策人按恢复规程处理。
- 续传时仅恢复通过边界，禁止重放取消或失败阶段的 notebook 单元格；保持现有变量快照安全行为。

#### 完成标准

- 单一子题缺少结果文件时，只重新执行该题；
- 已通过子题的哈希、冻结前证据和 checkpoint 不被删除；
- 连续失败不无限重试，也不会生成 Writer/PDF 伪成功产物。

### 阶段 D：冻结、写作与最终验收报告

#### 改动

- 保持 `frozen_results.json` 为 Writer 的唯一计算数值源；Writer prompt 不再引用未冻结的 Coder 自然语言结果。
- 新建 `backend/app/tools/final_acceptance.py`，生成：
  - `final_acceptance_report.json`；
  - `final_acceptance_report.md`。
- 报告应分别给出：
  - `TECHNICAL_PASS`：执行验证、冻结完整性、preflight、PDF visual check、严格字体、主交付文件、manifest 和完整源码附录均通过；
  - `TECHNICAL_FAIL`：列出每个硬失败及可定位 remediation；
  - `PENDING_HUMAN_REVIEW`：数学正确性、公式推导、引用真实性、规则适配、人工 PDF 翻阅和提交平台要求。
- 修改 `backend/app/tools/submission_audit.py`、`candidate_exporter.py`、`export_cli.py` 与 workflow 收尾步骤，使最终报告在 DOCX/PDF 全部刷新后生成。

#### 完整源码附录决策

当前 `append_code_appendix()` 明确截断源码，因此不能把既有自动报告称为最终验收通过。实施时采用以下规则：

1. 对最终提交 profile，附录写入完整、可运行、去除 notebook 输出后的源码；
2. 对过长代码，优先要求 Coder 生成模块化、简洁源码，而不是无提示截断；
3. 如竞赛官方规则最终允许源码仅作为支撑材料，应先更新 `CUMCM_FINAL_REVIEW_CHECKLIST.md` 和模板说明，再调整报告判定；在此之前严格遵守当前清单的“论文附录完整源码”要求；
4. 检查源码哈希、代码块完整性与附录实际内容，不能只检查附录 A 文件名。

#### 完成标准

- `final_acceptance_report` 不会把自动格式通过误称为数学正确或正式提交完成；
- 严格模式下，完整源程序缺失、字体 fallback、任何关键报告非 PASS 均为 `TECHNICAL_FAIL`；
- 人工核对项始终显式保留。

### 阶段 E：测试与真实验收

#### 单元与集成测试

新增或扩展以下测试：

| 测试 | 目的 |
| --- | --- |
| `test_model_plan_contract.py` | 验证正式问题键、题面参数、预期产物和验收指标完整性。 |
| `test_evidence_collector.py` | 验证路径隔离、有限数值、哈希、图表原始数据和跨题更新保护。 |
| `test_workflow_targeted_repair.py` | 验证仅失败题回修、重试次数、Writer 禁止提前执行。 |
| `test_execution_validation.py` | 保留并扩展专项 profile、不可行解和来源变更回归。 |
| `test_final_acceptance.py` | 验证严格字体、完整源码附录、四类主交付物和人工复核状态。 |
| LLM-free normal-task fixture | 使用工厂线性规划题产生真实 CSV、冻结和论文产物，覆盖 workflow 到 audit 的完整数据契约。 |

后端验证顺序：

```powershell
cd D:\workspace\MathModelAgent\backend
.venv\Scripts\python.exe -m unittest app.tests.test_problem_contract app.tests.test_execution_validation app.tests.test_workflow_execution_gate app.tests.test_result_integrity app.tests.test_submission_audit
.venv\Scripts\python.exe -m ruff check app
```

#### Docker 与真实任务验收

1. 先执行无模型 Docker 健康检查；
2. 运行工厂线性规划题，确认任务为 `completed` 且全部技术报告为 `PASS`；
3. 使用已验证 provider 再运行一次真实轻量任务；
4. 仅在指定决策人切换到已验证 provider 后，才恢复高压油管历史任务；不得连续自动重试同一失败 provider；
5. 正式提交前，用 Windows 本地正式字体重新导出，并由人工按最终清单复核。

## 5. 实施顺序与提交边界

建议按 A → B → C → D → E 顺序实施，每阶段都保持一条能生成 `res.md`、`res.json`、`res.docx` 的最小可交付路径。每阶段完成后：

1. 运行针对性单测和 Ruff；
2. 更新 `AGENT_MEMORY.md`，记录行为、验证命令和已知风险；
3. 如导出、模板、验收或使用命令变化，同步更新 `STARTUP.md`、PDF 模板说明、模板替换指南、最终复核清单及 export profile README；
4. 不提交、不推送，直至用户明确授权。

## 6. 最终验收门槛

技术验收只有同时满足以下项目才可标为 `TECHNICAL_PASS`：

- `/tasks` 对应任务为 `completed`；
- `res.md`、`res.json`、`res.docx`、`res.pdf`、`candidate_manifest.json` 存在且可读；
- `execution_validation_report.json = PASS`，冻结来源哈希仍有效；
- `paper_preflight_report.json = PASS`，关键完整性检查全部通过；
- `pdf_visual_check.json = PASS`；
- 严格字体模式下 `submission_audit_report.json = PASS`；
- 论文附录实际包含全部完整、可运行源程序；
- `final_acceptance_report` 明确列出待人工确认项目，且未出现硬失败。

完成技术验收后，仍必须由队员完成 `CUMCM_FINAL_REVIEW_CHECKLIST.md` 中的数学、引用、匿名、版式和提交平台人工复核。只有人工复核签署完成，任务才可被标记为“可正式提交”。

## 7. 实施记录（2026-07-14）

- 阶段 A--D 已落地：`ModelPlan` 覆盖校验、通用领域 profile、受控执行证据与后端 SHA-256、失败子题定向回修、完整源码附录和分层最终验收均已接入。
- 阶段 E 已补充回归：覆盖跨子题同名指标作用域、优化题缺少最优决策变量、完整源码中的正常 `print(...)`、附录 SHA 排版和最终验收。
- Docker 真实轻量线性规划任务 `20260714-021910-23c08616b2c6256627fcfd85fdb0f66c` 已实际运行到导出：`res.md`、`res.json`、`res.docx`、`res.pdf`、manifest、PDF 视觉检查均已生成；修复后 `pdf_visual_check.json = PASS`，完整源码附录检查通过。
- 该任务没有被误判为可验收：问题二只提交利润与残差、未提交新最优决策变量，新的执行门禁明确报出 `ques2.linear_programming_solution_metrics`；既有正文也因此保留真实的数值矛盾报告。必须从该 checkpoint 定向补齐问题二证据并重写受影响段落后，才可能达到 `TECHNICAL_PASS`；不得把本次产物用于正式提交。
