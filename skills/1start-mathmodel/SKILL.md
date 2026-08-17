---
name: 1start-mathmodel
description: "数学建模竞赛工作流入口。用于启动完整建模流程：询问用户偏好，生成 plan.md 和 todo.md，并按阶段调用赛题分析、建模、代码与图表、流程图、论文撰写、验证验收等 skills。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 数学建模工作流

本 skill 是数学建模竞赛项目的总控入口。它不替代后续阶段 skill，而是负责启动流程、询问偏好、记录决策、生成计划，并按顺序调用各阶段 skill。

## 数学建模规范参考

如需领域判断，读取 `../_references/math_modeling_norms.md`。该文件只提供数学建模基本规范和防错知识，不改变本 skill 的阶段顺序和产出约定。

## 必须产出

在当前工作目录中创建或更新以下文件：

- `plan.md`：整体流程方案、建模方向、阶段顺序、预期产物和风险控制。
- `todo.md`：具体待办事项列表，记录每个阶段的任务和状态。
- `reports/workflow_guard_report.json`：由本 skill 的 guard 生成的当前阶段、缺失交接物和推荐下游 skill。

## 工作流

### 1. 询问用户偏好 AskUserQuestions

在规划前，只询问会实质影响流程的问题。问题要少而关键。

优先询问（按重要性排序）：

1. **排版引擎**：Typst 还是 LaTeX？— 决定 5writing 使用哪套模板和编译命令。两套引擎均覆盖全部模板（14 中 + 3 英）。Typst 使用 `typst` 命令编译；LaTeX 使用 `xelatex` 命令编译（需跑两遍解决交叉引用）。
2. **竞赛类型**：国赛/华为杯/华中杯/MCM/...— 决定模板选择，见 5writing 的模板族清单。
3. **论文语言**：中文/英文 — MCM/ICM/COMAP 强制英文，其他默认中文。
4. **子问题数量是否已知**：影响章节文件生成数量。若未知，由 2analysis-modeling 阶段根据题面确定。

将用户的选择记录到 `plan.md` 的"方案"小节中。


### 2. 制定方案

按以下结构编写 `plan.md`：

```markdown
# 方案

要依次调用这些 skill，按照里面要求完成任务。

用户偏好：
- 排版引擎：<Typst / LaTeX>
- 竞赛类型：<国赛 / 华为杯 / MCM / ...>
- 论文语言：<中文 / 英文>
- 子问题数量：<已知 N 个 / 待分析确定>

workflow:
   step      skills
0. 选题路由（多题比较） - `0topic-selection`   # 仅当赛题未定时
1. 赛题分析与建模设计 - `2analysis-modeling`
2. 方法 PoC 验证与人工选型 - `2a-method-validation`
3. 编程实现和图表生成 - `3coding-visual`
4. 结果冻结与可追溯性 - `3a-result-freeze`
5. 流程与架构图绘制 - `4drawio`
6. 竞赛论文撰写 - `5writing`
7. 独立证据审计 - `6a-independent-audit`
8. 验证和验收 - `6verity`
```

## 项目目录结构

各阶段按此骨架创建和填充文件：

```text
.
├── plan.md                      # 1: 本文件
├── todo.md                      # 1: 待办事项
├── reports/                     # 各阶段文档报告
│   ├── ANALYSIS_MODELING_REPORT.md  # 1: 赛题分析-建模报告（2analysis-modeling）
│   ├── METHOD_VALIDATION.md          # 2: 候选 PoC 与比较（2a-method-validation）
│   ├── METHOD_SELECTION.md           # 2: 人工选型理由（2a-method-validation）
│   ├── RESULTS_REPORT.md             # 3: 结果报告（3coding-visual）
│   ├── frozen_numbers.json           # 4: 冻结指标与来源哈希（3a-result-freeze）
│   ├── DRAWIO_REPORT.md              # 5: 非数据图说明（4drawio）
│   ├── independent_audit_report.json # 7: 独立证据审计（6a-independent-audit）
│   ├── VERIFY_REPORT.md              # 8: 验收报告（6verity）
├── code/                        # 3: 代码（3coding-visual）
│   ├── problem1.py
│   ├── problem2.py
│   ├── problem3.py               # 问题的数量应该更具题目动态调整
│   ├── ... 
│   └── utils.py
├── results/                     # 3: 结果记录（3coding-visual）
├── figures/                     # 3+5: 所有图表（3coding-visual + 4drawio）
│   ├── *.pdf                    #     数据图 + 非数据图 PDF
│   ├── *.drawio                 #     非数据图源文件
├── paper/                       # 4: 论文（5writing）
│   ├── main.typ / main.tex      #     论文主文件（按用户选择的引擎）
│   └── sections/                #     各节文件（.typ 或 .tex）
```

方案必须明确每个阶段由哪个下游 skill 负责，以及该阶段应产出什么文件。

### 3. 生成待办

将 `todo.md` 写成阶段性 checklist，格式如下：

```markdown
# 待办事项

- [ ] 0. 选题路由（多题比较） - `0topic-selection`   # 仅当赛题未定时
- [ ] 1. 赛题分析与建模设计 - `2analysis-modeling`
- [ ] 2. 方法 PoC 验证与人工选型 - `2a-method-validation`
- [ ] 3. 编程实现和图表生成 - `3coding-visual`
- [ ] 4. 结果冻结与可追溯性 - `3a-result-freeze`
- [ ] 5. 流程与架构图绘制 - `4drawio`
- [ ] 6. 竞赛论文撰写 - `5writing`
- [ ] 7. 独立证据审计 - `6a-independent-audit`
- [ ] 8. 验证和验收 - `6verity`
```

每完成一个阶段，都要更新 `todo.md` 中对应任务的状态。

### 4. 依次执行阶段

每次首次启动、长对话恢复或不确定进度时，先运行 guard；不要根据聊天记忆猜测阶段：

```text
python "<1start-mathmodel skill 目录>/scripts/workflow_guard.py" --workspace .
```

读取 `reports/workflow_guard_report.json` 的 `recommended_skill` 和
`missing_prerequisites` 后再继续。该 guard 只检查实验性 skill 工作区的交接物，
不读取或修改 WebUI 的 `backend/project/work_dir/`。

按以下顺序调用下游 skills：

| 阶段 | Skill | 作用 | 主要产物 |
| --- | --- | --- | --- |
| 选题路由（多题比较） | `0topic-selection` | 赛题已发布、尚未决定做哪一道时，对 A/B/C 等多题横向比较建模路线、可行性、反驳条件与竞争力，阻塞式人工选题。 | `reports/TOPIC_SELECTION.md`, `reports/TOPIC_DECISION.md` |
| 赛题分析与建模设计 | `2analysis-modeling` | 解析题意、识别变量/约束/数据/评价指标，并建立数学模型、目标函数、约束条件和求解策略。 | `ANALYSIS_MODELING_REPORT.md` |
| 方法 PoC 验证与人工选型 | `2a-method-validation` | 用小型可复查 PoC 比较候选方法；由人工记录最终选型理由。 | `METHOD_VALIDATION.md`, `METHOD_SELECTION.md`, `code/poc/` |
| 编程实现和图表生成 | `3coding-visual` | 实现可复现代码，运行实验，生成结果表和多种多样的图表。 | `code/`, `results/` ,  `RESULTS_REPORT.md`, `figures/图表` |
| 结果冻结与可追溯性 | `3a-result-freeze` | 冻结写入论文的关键数值及来源哈希；来源变化时阻止继续使用旧结论。 | `frozen_numbers.json` |
| 流程与架构图绘制 | `4drawio` | 在论文确实需要时，绘制方法流程图、架构图和非数据型概念图。 | `figures/*.drawio`, `figures/*.pdf`, `DRAWIO_REPORT.md` |
| 竞赛论文撰写 | `5writing` | 基于分析、建模、代码结果和图表撰写最终竞赛论文，并按章节直接插入图表。 | `paper/` |
| 独立证据审计 | `6a-independent-audit` | 独立核查冻结来源、指标语义、论文与图表的基本可追溯性。 | `independent_audit_report.json/md` |
| 验证和验收 | `6verity` | 检查可复现性、一致性、产物完整性、格式规范和提交就绪状态。 | `VERIFY_REPORT.md` |

## 多智能体 / Subagent 调用限制（Codex spawn_agent）

本 skill 的 `allowed-tools` 包含 `Agent`，可用于调用 Codex 内置的
`spawn_agent`。当前接口使用 `fork_context` 布尔字段控制上下文继承，不能使用
`fork_turns` 参数。为控制 token 消耗和任务复杂度，必须遵守以下规则：

- 主 agent 创建子任务时必须显式传入 `fork_context:false`；严禁使用
  `fork_context:true`，确保子 agent 不继承父线程上下文。
- 只有主 agent 可以调用 `spawn_agent`（或 `Agent` 工具）；subagent 不得再创建
  subagent 或形成嵌套任务树。需要追加拆分时，先将建议和阶段摘要交回主 agent。
- 同一时刻活动的直接 subagent 最多 5 个；本工作流的 8 个阶段默认串行执行，只允许将
  互不依赖的旁路任务有限并行，不能为了加速无边界拆分。
- 子 agent 只接收阶段摘要、明确目标和文件路径；不得回灌整段工具输出、完整父对话或无关上下文。
- 真实建模任务如需断点续传，优先走后端 `POST /modeling`，不要把 Codex 原生子线程当作
  项目级 checkpoint 机制。
- 发起多智能体调用前，确认当前账户或代理具备经用户授权的隔离计费与预算限制；未确认时不得 spawn。

## 阶段边界

- `3coding-visual` 负责生成所有依赖计算结果或实验输出的数据图表。
- `4drawio` 只负责概念图、算法流程图、架构图、路线图等非数据型图示。
- 不要让 `4drawio` 重复绘制 `3coding-visual` 已经生成的统计图或数据图。
- `5writing` 负责决定图表在论文中的位置，并按所选引擎写入图表代码：
  - Typst：`#figure(image("../../figures/xxx.pdf", width: 85%), caption: [...])`
  - LaTeX：`\begin{figure}[H]\centering\includegraphics[width=0.85\textwidth]{../../figures/xxx.pdf}\caption{...}\label{fig:xxx}\end{figure}`
- 不要让 `5writing` 编造数值结论。论文中的数值必须来自 `RESULTS_REPORT.md`、结果表或已生成图表的数据。
- 启用结果冻结后，`5writing`、`6a-independent-audit` 和 `6verity` 必须以 `frozen_numbers.json` 为关键数值的来源基线；它只能证明来源未变化，不能证明数学模型正确。
