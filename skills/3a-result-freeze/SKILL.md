---
name: 3a-result-freeze
description: "Freeze validated mathematical-model metrics with source hashes after coding and before diagramming or paper writing. Use when results must remain traceable across later workflow stages."
---

# 结果冻结与可追溯性

在 3coding-visual 生成并核对结果后、4drawio 和 5writing 使用这些结论前，冻结关键指标和它们的可重复来源。冻结不是重新求解，也不代替人工判断模型是否正确。

## 输入与产物

先创建一个只包含准备写入论文的关键指标的 JSON 文件。推荐格式如下：

~~~
{
  "metrics": [
    {
      "id": "objective_value",
      "value": 2200,
      "unit": "yuan",
      "explanation": "最优生产方案对应的总利润"
    }
  ]
}
~~~

运行脚本时显式提供该 JSON 和一个或多个可重复来源文件。来源可以是结果报告、CSV、求解输出或生成图表的数据文件；不要把 API key、cookie、原始隐私数据或凭据文件作为来源。

~~~
python "<skill-dir>/scripts/freeze_results.py" ^
  --workspace . ^
  --metrics reports/key_metrics.json ^
  --source reports/RESULTS_REPORT.md ^
  --source results/summary.csv ^
  --output reports/frozen_numbers.json
~~~

在 Unix shell 中把续行符 ^ 改为 \。脚本只把指标、工作区相对路径和 SHA-256 写入冻结文件，不复制来源文件正文。

## 工作流

1. 从 reports/RESULTS_REPORT.md、结果表和代码输出提取有限且可解释的关键指标。
2. 确认每个准备写入论文的指标包含 id、value、unit、explanation。
3. 运行冻结脚本，并把 reports/frozen_numbers.json 作为后续绘图、写作和审计的唯一数值基线。
4. 在继续下游阶段前验证冻结快照：

~~~
python "<skill-dir>/scripts/freeze_results.py" ^
  --workspace . ^
  --verify ^
  --output reports/frozen_numbers.json
~~~

5. 如果验证失败，不要继续沿用旧论文数值。先重新核对代码或数据，再重新冻结并标记下游图表、论文和审计需要复核。

退出码 0 表示验证通过；非零表示来源缺失、来源已变化或冻结文件无效。验证结果会以 JSON 输出，便于 workflow guard 或人工复核读取。
