---
name: 2a-method-validation
description: "Validate and compare mathematical-modeling method candidates with small reproducible PoCs and a mandatory human selection gate. Use after model design and before full implementation when competing methods, assumptions, or data feasibility need evidence."
---

# 方法 PoC 验证与人工选型

在完整实现和论文写作前，用可复现的小型证据淘汰不合适的方法；不要把 PoC 当作最终求解或自动决策。

## 产物位置

只在**当前任务工作目录**创建或更新下列产物，绝不把任务证据写进本 skill 目录：

- `reports/METHOD_VALIDATION.md`：候选、数据来源、PoC、检查结果和失败记录。
- `reports/METHOD_SELECTION.md`：待人工填写的比较与选型决定。
- `code/poc/<candidate-id>_poc.<ext>`：确有必要时的最小 PoC。
- `results/method_poc/<candidate-id>.*`：PoC 的可复查输出、表格或图。

## 工作流

### 1. 建立候选集

从题面、附件和 `ANALYSIS_MODELING_REPORT.md` 提出 2–4 个可区分的候选；若题目已唯一限定方法，仍记录该方法和一个可行的基线或说明为什么不存在替代项。为每个候选在 `METHOD_VALIDATION.md` 记录：

- `candidate-id`、解决的子问题、核心假设、输入、目标/约束和预期输出；
- 可证伪的检查，例如可行性、量纲、边界行为、留出误差、约束满足或已知小例；
- 适用条件、主要风险，以及失败后改回哪个分析问题。

不要以名称相近的算法充数；候选必须在假设、目标、约束处理或数据需求上有实际差异。

### 2. 运行最小 PoC

优先为每个候选使用一个单文件、可独立阅读的 PoC，目标是不超过约 30 行**可执行非空代码**。仅当求解器初始化、数据读取或必要校验使其无法做到时才超出，并在报告中写明原因。简单题可用手算表或已有运行结果代替代码，但仍须保存输入、步骤和输出。

先声明数据证据等级：

- **实际数据**：记录任务目录内的相对路径、覆盖范围/样本量、必要清洗和切分；只报告该实际输入上得到的结果。
- **合成数据**：明确标为 `synthetic`，记录生成规则、参数和随机种子（如有）。只用它检查算法行为、边界和可行性，绝不将其指标表述为真实任务表现。
- **无数据题**：把题面给定参数标为 `given-parameters`，做单位、约束和极端值核验；不得伪造样本来声称验证了拟合或预测能力。

每次 PoC 都记录命令或手算步骤、输入标签、输出位置、检查结论和限制。优先使用项目已有环境或语言标准库；不要为了 PoC 新增外部依赖或大规模训练。

### 3. 比较并暂停在人工门禁

在 `METHOD_SELECTION.md` 放入候选比较表，至少含候选、PoC 状态、数据证据等级、关键结果、适用性、风险和推荐意见。初始状态写为 `PENDING_HUMAN_SELECTION`。

只有人工审阅者填写以下全部内容后，才可把状态改为 `SELECTED` 并进入完整实现：

```markdown
## Human decision
- Selected candidate: <candidate-id>
- Reviewer: <name or role>
- Date: <YYYY-MM-DD>
- Rationale: <nonempty rationale citing a PoC result and an assumption/risk trade-off>
```

`Rationale` 不得为空、不得只写“同意”“最好”或引用表格；没有人工决定时保持阻塞，不得由模型自行选择或开始最终论文结论。

## 失败规则

- 缺少候选定义、输入来源、可证伪检查或可复查输出的 PoC 为 `FAIL`；补正后重新记录，保留原失败原因。
- 实际数据缺失时可运行合成 PoC，但把对应候选标为 `CONDITIONAL`，不得据此声称已验证真实效果。
- PoC 违反题面约束、量纲不成立、无法复现、或一次针对性修正后仍失败时，淘汰该候选并说明回退的分析问题。
- 所有候选失败、或唯一候选只具合成证据而任务需要实际数据时，状态为 `BLOCKED`：回到分析阶段补充假设/数据，不得强行选型。
- 人工理由缺失、选择了失败候选、或理由未引用证据时，状态保持 `PENDING_HUMAN_SELECTION`。

## 完成条件

在交给代码阶段前，确认 `METHOD_VALIDATION.md` 覆盖每个候选，`METHOD_SELECTION.md` 有非空人工理由，且所选候选未失败；把其输入、约束和验证口径交给后续实现阶段。
