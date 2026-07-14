---
name: 6a-independent-audit
description: "Audit frozen mathematical-model results independently for source-hash integrity, metric semantics, and basic paper or figure traceability. Use after paper drafting and before final verification when a result-freeze evidence chain is active."
---

# 独立证据审计

在 `5writing` 后、`6verity` 前，独立审阅 `3a-result-freeze` 的工件。审计只确认
关键指标有来源、来源未变化、字段可解释以及可选论文/图表路径存在；它**不证明**模型、
算法、公式、数据理解或结论正确。

## 输入与产物

在当前任务工作区读取：

- 必需：`reports/frozen_numbers.json`。
- 可选：论文入口或 Markdown 源稿、`figures/`。

写入：

- `reports/independent_audit_report.json`
- `reports/independent_audit_report.md`

脚本只写入工件名、哈希检查与指标标识，不复制结果来源或论文的全文。

## 运行

先在任务工作区运行；把 `<skill-dir>` 替换为本 skill 的实际路径：

```text
python "<skill-dir>/scripts/independent_audit.py" ^
  --workspace . ^
  --freeze reports/frozen_numbers.json ^
  --paper paper/main.tex ^
  --figures-dir figures
```

Unix shell 将续行符 `^` 改为 `\`。`--paper` 和 `--figures-dir` 可省略；若显式
提供却不存在，报告为 `FAIL`。退出码为 0（`PASS` 或 `WARN`）或非 0（`FAIL`）。

## 审计规则

1. 冻结文件必须是 `mathmodel.result-freeze` schema、版本 1，且有非空 `metrics` 和 `sources`。
2. 每个指标必须有 `id`、非空 `value`、`unit` 和 `explanation`；缺失字段不能靠审计器推断。
3. 每个来源必须留在工作区内、存在，并与冻结的 SHA-256 一致。
4. 可选论文或图表目录只做路径/非空性检查。指标如何被正文论证、图表是否表达正确，仍由人工复核。
5. `FAIL` 必须回到结果、冻结或写作阶段修复；`WARN` 必须在最终人工复核中接受或处理。

## 完成条件

将 JSON/Markdown 报告交给 `6verity`。只有哈希未变化、指标语义完整且没有 `FAIL` 时，
才可把证据链视为技术上可追溯；这不是数学正确性的批准。
