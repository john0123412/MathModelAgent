---
name: 4drawio
description: "数学建模非数据型图示绘制阶段。根据 ANALYSIS_MODELING_REPORT.md、RESULTS_REPORT.md 和已有 figures/ 生成技术路线图、子问题求解流程图、模型结构图、数据处理流程图等 DrawIO 图，并导出论文可引用 PDF。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# DrawIO 非数据图示绘制

本 skill 承接 `3coding-visual`。它只负责论文中的**非数据型图示**，例如技术路线图、求解流程图、模型结构图、数据处理流程图、变量关系图、指标体系图等。

## 数学建模规范参考

如需领域判断，读取 `../_references/math_modeling_norms.md` 中的“图表与可视化”和“非数据图工具选择”小节。该文件只作为规范知识库，不要求为了凑数量生成额外图示。

## 阶段边界

- 本阶段负责：DrawIO 源文件、非数据图 PDF、图示生成记录。
- 本阶段不负责：折线图、柱状图、散点图、热力图、箱线图、雷达图等数据图。这些由 `3coding-visual` 生成。
- 本阶段不重跑模型、不修改 `code/`，不改写 `reports/RESULTS_REPORT.md` 的数值结论。

## 必须产出

在当前工作目录创建或更新：

```text
figures/
  fig_roadmap.drawio
  fig_roadmap.pdf
  fig_flow_q1.drawio
  fig_flow_q1.pdf
  ...
reports/DRAWIO_REPORT.md
```

如果某类图不需要生成，必须在 `reports/DRAWIO_REPORT.md` 中说明原因。竞赛论文通常至少需要一张 `fig_roadmap` 技术路线图。

读取这些文件的目的不是提取数据作图，而是理解论文方法、章节结构、子问题关系和已有图表，避免重复。

## 工作流程

### Step 1: 盘点已有图表和需求

先读取以下文件（存在则读取）：`reports/ANALYSIS_MODELING_REPORT.md`、`reports/RESULTS_REPORT.md`、`figures/` 目录列表。

然后从前序文档提取非数据图需求，输出一个清单：

```text
DRAWIO PLAN CHECKLIST:
[ ] fig_roadmap      技术路线图，放在问题重述/绪论
[ ] fig_flow_q1      问题一求解流程图
[ ] fig_flow_q2      问题二求解流程图
[ ] fig_flow_q3      问题三求解流程图
[ ] fig_pipeline     数据处理流程图
[ ] fig_model        模型结构/变量关系图
```

清单不是固定模板，要根据题目实际删减或增补。不要为了凑图生成无意义图示。

### Step 2: 判定图类型

常见图示选择：

| 图类型 | 文件名建议 | 适用场景 |
| --- | --- | --- |
| 技术路线图 | `fig_roadmap` | 展示整体解题路线、章节逻辑、方法串联 |
| 子问题求解流程图 | `fig_flow_q1`, `fig_flow_q2` | 展示单个子问题的输入、判断、算法、输出 |
| 数据处理流程图 | `fig_pipeline` | 展示数据清洗、特征构造、建模输入 |
| 模型结构图 | `fig_model` | 展示模块关系、变量关系、模型层次 |
| 指标体系图 | `fig_index_system` | 展示目标层、准则层、指标层 |
| 决策树/规则图 | `fig_decision_tree` | 展示分类规则、设备选择、策略分支 |

不要用 DrawIO 画这些图：

- 结果对比柱状图
- 预测误差曲线
- 灵敏度曲线
- 相关性热力图
- 分布图和箱线图

### Step 3: 生成 DrawIO 源文件

每张图一个 `.drawio` 文件，放在 `figures/`。

**优先套用内置模板**（本 skill 附带 5 个模板生成器，纯标准库；内容 JSON 从
`reports/ANALYSIS_MODELING_REPORT.md` 与 `reports/RESULTS_REPORT.md` 抽取，
不要编造）：

| 模板 id | 版式 | 适合表达 |
|---|---|---|
| `roadmap-5band` | 954×1296 竖版五带 | 提出问题 → 数据与指标 → 方法与机制 → 结果对比 → 评价推广 |
| `roadmap-3phase` | 竖版三阶段 + 问题导轨 | 数据与指标 → 两组建模预测 → 情景与路径规划 |
| `framework-3col` | 三栏内容全景 | 每个阶段对应哪些研究内容、用什么方法 |
| `stageflow-3col` | 三栏执行流程 | 阶段推进、决策分支、成果分发 |
| `taskflow-land` | 横版任务流水线（16:9） | 任务一…任务四，每步方法与结论 |

```bash
# 复制 assets/<模板id>/example.json 改写槽位文字后渲染（语义约定与字数预算见对应 references/<模板id>.md）
python "$SKILL_DIR/scripts/roadmap_5band.py" content.json -o figures/fig_roadmap.drawio
```

五个模板默认输出灰白论文版，加 `--theme color` 还原彩色演示风格。语义放错比字数超框严重——
先读对应 `references/<模板id>.md` 的"语义约定"与"字数预算"两节再动笔。

不适配任何模板的图示（模型结构、指标体系、决策规则等）从零手写 XML，骨架、样式速查、
中文字宽预算、连接器写法见 `references/authoring.md`；图标等特殊图元见 `references/icons.md`；
高保真复刻参考图按 `references/replication.md` 执行。三条路的产物可互相接着改。

DrawIO 内容要求：

- 文字语言与论文语言一致。
- 节点文字短，必要时双行，不堆长句。
- 同类节点样式统一。
- 箭头方向清晰，避免交叉。
- 图中不写大段解释，解释留给论文正文。
- 不使用装饰性阴影和过度渐变。

生成大 XML 时，分段写入，避免截断。示例：

```bash
mkdir -p figures
cat << 'XMLEOF' > figures/fig_roadmap.drawio
<mxfile>
  <diagram name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- nodes and edges -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
XMLEOF
```

### Step 4: 导出 PDF

优先用可用的 DrawIO 命令导出 PDF：

```bash
DRAWIO_BIN="$(command -v drawio 2>/dev/null || command -v draw.io 2>/dev/null || command -v draw.io.exe 2>/dev/null || true)"
if [ -n "$DRAWIO_BIN" ]; then
  "$DRAWIO_BIN" --export --format pdf --crop --output figures/fig_roadmap.pdf figures/fig_roadmap.drawio
else
  echo "DrawIO command not found; keep .drawio source and record export failure."
fi
```

也可用本 skill 附带工具替代手工导出流程：

```bash
python "$SKILL_DIR/scripts/export_figure.py" figures/fig_roadmap.drawio   # 1:1 PNG + 矢量 PDF（仍需 drawio 命令行）
python "$SKILL_DIR/scripts/preview_html.py" figures/fig_roadmap.drawio    # 浏览器预览，无需 drawio 命令行
```

如果无法导出 PDF，保留 `.drawio`，在 `reports/DRAWIO_REPORT.md` 记录失败原因和建议导出命令。

### Step 5: 自检和修复

**先过静态版式门禁**（本 skill 附带，中文字宽模型，正常图应达 FAIL 0 / WARN 0；
`--strict` 下 WARN 也算失败，作为交付门禁必须通过）：

```bash
python "$SKILL_DIR/scripts/check_layout.py" figures/fig_roadmap.drawio --strict
```

报警就值得认真看：FAIL 覆盖文字溢出、元素越界、id 重复、盒子重叠、连线穿盒、内嵌位图；
WARN 覆盖端点压盒边、疑似空盒、字号/配色发散。规则详解与规避手法见
`references/preflight-rules.md`。门禁不通过时修 `.drawio` 后重跑，直到 FAIL 0 / WARN 0。

然后逐张检查：

- `.drawio` 文件非空。
- 若导出成功，`.pdf` 文件非空。
- 节点没有明显重叠。
- 箭头不穿过核心节点。
- 字号、颜色、边框风格一致。
- 文件名和图意一致。
- 没有与 `3coding-visual` 的数据图重复。

发现问题要修 `.drawio` 并重新导出，不要只在报告里解释。

### Step 6: 写生成记录

创建 `reports/DRAWIO_REPORT.md`，至少包含：

```markdown
# DrawIO 图示生成报告

## 图示清单
| 文件 | 类型 | 来源依据 | 用途 | 状态 |
| --- | --- | --- | --- | --- |

## 未生成图示及原因

## 导出与自检记录

## 给论文阶段的嵌入建议
```

嵌入建议只说明每张图适合放入哪个章节和建议 caption，不生成 `*_typst_includes.typ`。最终的图表插入代码（Typst 的 `#figure(image(...), caption: [...])` 或 LaTeX 的 `\begin{figure}...\end{figure}`）由 `5writing` 根据论文结构和所选引擎决定。

## 内置实现资产索引

```text
scripts/
  roadmap_5band.py roadmap_3phase.py framework_3col.py stageflow_3col.py taskflow_land.py
                                                    # 5 个模板生成器（content JSON -> .drawio）
  check_layout.py                                   # 版式门禁：溢出/越界/重叠/穿盒/位图（--strict 作交付门禁）
  export_figure.py                                  # drawio 命令行导出 PNG/PDF
  preview_html.py                                   # 本地浏览器预览，无需 drawio 命令行
assets/<模板id>/example.json + preview.png           # 各模板示例内容与效果图
assets/icons/tabler/                                 # tabler 图标库子集（见 ATTRIBUTION.md）
references/                                          # authoring / icons / 各模板说明 / replication /
                                                     # self-check / preflight-rules / adding-templates
```

## 质量要求

- 图示服务论文论证，不为装饰而画。
- 每张图必须能对应到`reports/ANALYSIS_MODELING_REPORT.md` 中的真实方法。
- 数据型图表不得在本阶段重复生成。
- 论文阶段引用的非数据图都应有 `.drawio` 源文件和 PDF，或者在 `reports/DRAWIO_REPORT.md` 说明导出失败。
