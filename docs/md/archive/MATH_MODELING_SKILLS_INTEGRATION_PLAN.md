> [已归档 2026-09-06] 本文档为一次性接入方案,状态:结论有效、实施细节以现状为准,内容不代表当前系统行为;索引见 docs/md/archive/README.md。

# math-modeling-skills 外部完善层接入方案

## 结论

`D:\workspace\math-modeling-skills` 可以沿用，但推荐定位为 **MathModelAgent 自动生成后的独立完善与审计层**，不替换主项目的 Modeler/Coder/Writer、执行证据、checkpoint、冻结结果和导出 profile。

## 职责边界

```text
MathModelAgent
  建模 → 代码执行 → execution validation → frozen results
  → Writer → res.md/res.json/res.docx/res.pdf
  → candidate_manifest.json (schema 1.1 + hashes)
                    │
                    │ 只读文件包交接
                    ▼
math-modeling-skills
  claims / constraints / figures / reproducibility / AI usage
  → Typst 或 LaTeX 精修
  → compile_paper.py + run_preflight.py
                    │
                    ▼
人工模型、数学、引用、逐页 PDF 与提交规则确认
```

## 为什么不直接合并 orchestrator

- 两个项目都包含模型选择、求解、写作调度，直接嵌套会形成双重调度和状态冲突。
- MathModelAgent 已有任务状态、checkpoint、变量快照、执行证据与冻结结果；这些能力不应由外部 skills 重做。
- 文件包交接容易版本化、留档和回退，也能用 `artifact_set_id` / SHA-256 判断外部精修是否基于同一候选。

## 推荐目录

```text
D:\workspace\math-modeling-skills\examples\<task-name>\
├── external_candidates\mathmodelagent\<task-id>\
│   ├── candidate_manifest.json
│   ├── res.md
│   ├── res.json
│   ├── res.docx
│   ├── res.pdf
│   ├── frozen_results.json
│   ├── execution_validation_report.json
│   └── figures-and-data\...
├── outputs\tables\
│   ├── summary.json
│   ├── metrics.json
│   ├── paper_claims.json
│   ├── constraints.json
│   ├── figure_table_plan.json
│   └── figure_table_manifest.json
├── typst_project\main.typ
├── latex_project\main.tex
├── ai_usage\ai_usage_log.md
└── outputs\paper.pdf
```

原始候选目录应保持只读；精修产物写入 skills 示例目录，不反向覆盖 MathModelAgent 的任务目录。

## 三阶段落地

### 阶段 1：立即可用的人工文件包流程

1. 确认 MathModelAgent 的 `final_acceptance_report.json` 技术状态，并读取 `candidate_manifest.json`。
2. 将 manifest 登记的文件复制到 `external_candidates/mathmodelagent/<task-id>/`。
3. 人工将冻结指标映射为 `paper_claims.json`，将执行验证/约束 CSV 映射为 `constraints.json`，将图片及正文引用映射为 `figure_table_manifest.json`。
4. 使用 `07-paper-writing-cumcm`、`08-code-reproducibility`、`09-ai-usage-logging`、`10-paper-typesetting` 做独立精修。
5. 编译并运行 skills 的确定性检查，最后由人工签字。

### 阶段 2：轻量导入适配器

建议未来只在 skills 仓库新增以下适配器，不修改其现有 orchestrator：

```text
src/adapters/mathmodelagent/
├── import_candidate.py
├── normalize_claims.py
├── normalize_constraints.py
├── normalize_figures.py
└── schema.md
```

适配器应先验证 `candidate_manifest.json.schema_version`、`artifact_set_id` 与 `artifact_hashes`，再生成 skills 所需 JSON；任何哈希不一致都停止导入。

### 阶段 3：版本化离线协议

- 保持文件级交接，不做实时 RPC。
- 对 candidate schema 和 skills normalized schema 分别版本化。
- 外部精修后的 PDF 生成新的 handoff manifest，记录上游 `artifact_set_id`、精修源文件和最终 PDF 哈希。
- 不让 skills 重新调用 MathModelAgent Writer/Modeler/Coder；需要重算时回到主项目生成新候选包。

## 推荐检查命令模板

以下命令在 skills 已建立 `.typ` 或 `.tex` 精修项目、并完成 JSON 适配后使用：

```powershell
cd D:\workspace\math-modeling-skills

.venv\Scripts\python.exe scripts\check_paper_claims.py `
  --paper-source examples\<task>\typst_project\main.typ `
  --claims examples\<task>\outputs\tables\paper_claims.json

.venv\Scripts\python.exe scripts\check_constraints.py `
  --constraints examples\<task>\outputs\tables\constraints.json

.venv\Scripts\python.exe scripts\check_figure_table_assets.py `
  --manifest examples\<task>\outputs\tables\figure_table_manifest.json `
  --paper-source examples\<task>\typst_project\main.typ `
  --min-figures 1 --min-tables 1

.venv\Scripts\python.exe scripts\compile_paper.py `
  examples\<task>\typst_project\main.typ --check

.venv\Scripts\python.exe scripts\run_preflight.py `
  --strict full --final `
  --paper-source examples\<task>\typst_project\main.typ `
  --pdf examples\<task>\outputs\paper.pdf `
  --claims examples\<task>\outputs\tables\paper_claims.json `
  --constraints examples\<task>\outputs\tables\constraints.json `
  --figure-manifest examples\<task>\outputs\tables\figure_table_manifest.json
```

`check_figure_table_assets.py` 默认要求 5 图 4 表；轻量题应显式设置与题目规模一致的阈值，不能为了通过检查制造无意义图表。

## 优先复用的 skills 与脚本

- `08-code-reproducibility`：环境、运行入口、输出与断言复核。
- `09-ai-usage-logging`：记录 AI 使用边界，不写入密钥正文。
- `07-paper-writing-cumcm` / `10-paper-typesetting`：独立排版与提交前精修。
- `scripts/check_paper_claims.py`：论文数值声明对证据表。
- `scripts/check_constraints.py`：硬约束状态。
- `scripts/check_figure_table_assets.py`：图表清单与正文同步。
- `scripts/check_paper_sync.py`：PDF 与源文件/产物时间同步。
- `scripts/compile_paper.py`、`scripts/run_preflight.py`：最终编译和综合预检。

## 必须保留的人工门禁

- 模型假设与题意是否正确；
- 坐标顶点、约束归属、单位和影子价格区间；
- 连续解与整数实施口径；
- 引用是否真实且实际支撑对应段落；
- 图表与正文引用闭环；
- PDF/DOCX 逐页排版、匿名要求和当年官方提交规则。
