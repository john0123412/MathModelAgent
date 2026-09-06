# CUMCM 2026 模板替换指南

## 当前状态

- 当前 `cumcm2026` 是基于《全国大学生数学建模竞赛论文格式规范（2026年修订稿）》实现的暂定模板，不是官方最终 DOCX/LaTeX 模板包。
- 主 PDF 按 2026 修订稿口径实现：电子版不生成目录，摘要页作为第一页；主 PDF 与 LaTeX sidecar 均禁 raw TeX，支持 `$...$` 和 `\(...\)` 数学公式，自动编译禁用 shell escape。
- Writer 完稿后会生成非阻断的、profile-aware `semantic_layout_review.json/md`：`cumcm2026` 提示“一、”至“七、”及“附录”必须使用一级标题、1.1/5.1.1 等小标题层级应与 PDF 书签一致，并提示空引用或疑似原始文件名图题；该提示不替代实际 PDF 视觉和书签复核。
- 主 PDF 会在摘要/关键词后及附录前做 PDF-only 分页，保证摘要页独占第一页、正文从第二页开始且附录另起页；该分页不写回 `res.md`，也不影响 DOCX 或 LaTeX sidecar。
- 当前 DOCX reference 暂时复用 2025：
  `backend/app/templates/export_profiles/cumcm2025_docx/format2025_reference.docx`
- 当前 LaTeX sidecar 使用 `backend/app/tools/tex_project_exporter.py` 中的
  `_CUMCM2026_MAIN_TEX_TEMPLATE` 无封面 `ctexart` 外壳，不复用 2025
  `gmcmthesis`；后者的 `\maketitle` 会生成含学校、队号、队员字段的旧式封面，
  不符合 2026 电子版“摘要页为第一页、不得放承诺书和编号专用页”的要求。默认、CUMCM
  2025/2026 与华数杯 sidecar 均将 `listings` 代码字号统一为 `\ttfamily\footnotesize`，并开启自动换行，减少完整源码附录出现孤立尾页。2026 外壳同时加载 `array` 与 `calc`，用于兼容 Pandoc 生成的 longtable 列宽代码中的 `\arraybackslash` 和 `\real{}`。
- 当前 LaTeX sidecar 导出器会复制正文引用的本地图片到 `latex_project/` /
  `latex_project/figures/`，并在 `tex_export_status.json` 记录 `copied_assets` /
  `missing_assets`；Windows bind mount 拒绝 `copy2` 元数据时会退化为字节复制，
  自动编译前会清理明确列举的旧辅助文件，避免陈旧 `.aux` 破坏新稿。
- 当前复用的 `gmcmthesis.cls` 对 `KaiTi` / `STXinwei` / `LiSu` 做了容器友好的
  fontspec fallback；若缺少 Windows 字体和 `AR PL KaitiM GB`，会继续 fallback 到
  Noto CJK 字体，优先保证 sidecar 可编译。
- 主交付链路是：
  `res.md`
  `res.pdf`
  `res.docx`
  `res.json`
  `candidate_manifest.json`
- `candidate_manifest.json -> submission_file` 是唯一主上传文件（默认 `res.pdf`）；如平台允许另交支撑材料，再使用受控的 `support_materials_manifest.json` / `support_materials.zip`，不得把 ZIP 当成论文主文件。
- `reference_sources` 只记录 DOI/URL 基本格式和本地来源哈希，`similarity_ai_risk` 只提示本地草稿风险；两者都不能替代人工来源核验或比赛指定的正式查重/AI 审核。
- `latex_project/` 是候选 sidecar，不是当前主交付链路。
- 当前 `paper_postprocessor.append_code_appendix()` 默认在附录 B 写入任务目录发现的完整可运行脚本及 notebook 代码单元（不含 notebook 输出），逐份记录原始 SHA-256；`final_acceptance_report.json -> complete_source_appendix` 会核对源码覆盖、哈希和正文代码内容。若启用 `paper_appendix_config.json -> mode=key`，只展示关键算法，技术验收会刻意保持非 `TECHNICAL_PASS`，正式提交必须恢复 `full`。
- 自动完整性门禁仍不能替代人工运行源码、核对数学推导与数值、逐页审查 PDF/DOCX 和确认比赛平台最终规则；`TECHNICAL_PASS` 仍标记 `PENDING_HUMAN_REVIEW`。

## 任务级导入：不改公共模板的临时覆盖

当前 `cumcm2026` 和 `cumcm2025` 是仓库内可复现的 profile；如果比赛临近又取得了新的
Word 参考模板，或队伍需要为一个已完成任务记录某份中文竞赛格式，优先使用任务级覆盖，
不要直接替换 `backend/app/templates/export_profiles/`。导入文件会复制进该任务的
`template_overrides/`，并由 `export_template_override.json` 绑定 DOCX 与合同 SHA-256；
`template show` 会在导出前重新校验。该接口只接受安全 `.docx`，不接受 `.doc`、符号链接、
不安全的压缩包路径或任意 TeX；当前只支持 `cumcm2025`、`cumcm2026`。

在 `backend/` 中执行以下完整闭环（`task-refresh` 是必需步骤）：

```powershell
cd D:\workspace\MathModelAgent\backend
uv run python -m app.tools.export_cli template install `
  --task-id <task_id> --profile cumcm2026 `
  --docx-template "D:\format-package\official.docx" `
  --format-contract "D:\format-package\format.json" `
  --label "用户指定中文竞赛格式基线 2026-08"
uv run python -m app.tools.export_cli template show `
  --task-id <task_id> --profile cumcm2026
uv run python -m app.tools.export_cli task-refresh `
  --task-id <task_id> --profile cumcm2026 --local
```

刷新不会调用 Provider，也不会重新执行题目代码；它只重建 Markdown、DOCX、PDF、LaTeX
sidecar、预检、视觉检查、submission audit、candidate manifest 和最终技术验收。若合同或
模板哈希不匹配，先重新导入，不要手改 `export_template_override.json`。Docker 调用时，
官方文件和合同必须先放入容器可见的任务目录（例如
`/app/project/work_dir/<task_id>/`）。

合同示例见 [`docs/md/竞赛版式合同示例.json`](竞赛版式合同示例.json)。其
`schema_version` 必须为 `mma.export-format-contract.v1`；允许的 PDF 变量只有字体、字号、
行距、`geometry`、A4 等安全字段，DOCX 只记录字体/字号/行距/正文起始分页，`preflight` 只
记录摘要段数、参考文献开关和正文页数范围。系统会将导入合同标为
`source=user_supplied_unverified`、`official_rule=false`，不能因为文件名或 `label` 写了
“official”就宣称官方认证。

当前用户指定的中文论文基线为：摘要正文和正文 prose 使用宋体小四（12pt）、单倍行距；摘要至少
分为两段，关键词后从“问题重述”开始另起页；正文（不含摘要、参考文献和附录）按 15--30 页做
严格完整性检查（30 页上限对齐 CUMCM 2026 官方口径，15 页下限为用户指定的内部严格门禁）；参考文献必须存在且按正文首次引用顺序编号。它是应用的可机检基线，而不是对
CUMCM 当年官方格式的声明；最新官方包若不同，应由队员核实后将允许的版式字段写入合同，再执行
`template install`、`template show` 和 `task-refresh`。

这里的中文竞赛格式是用户指定基线；`huashubei` 仅供华数杯参考，不能当作 CUMCM 高教社杯
官方格式。无论使用仓库内置 profile 还是任务级覆盖，比赛前一天和提交前都必须打开最新
官方包、官方公告及提交系统，人工核对字体、边距、摘要页、匿名字段、文件命名和大小限制。

## 官方资料入口

- 官方首页：
  `https://www.mcm.edu.cn/`
- 2026 论文格式规范页面：
  `https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html`
- 2026 参赛规则页面：
  `https://www.mcm.edu.cn/html_cn/node/9d8e511fe7a1447b35f53a82c908e2e0.html`
- 2026 第一次通知页面：
  `https://www.mcm.edu.cn/html_cn/node/d6fd7a0ee8f3a3d525e30af1c365fcec.html`
- 知网报名与提交入口：
  `https://cumcm.cnki.net`

比赛前一天和比赛当天必须重新检查这些入口，确认是否新增 DOCX/Word 模板、LaTeX 模板、承诺书/编号页模板、提交系统特殊要求。

## 关键代码路径速查表

| 用途 | 当前路径 | 说明 | 官方模板发布后如何改 |
|---|---|---|---|
| 导出 profile 定义 | `backend/app/tools/export_profiles.py` | `CUMCM2026_PROFILE` 定义主 PDF/DOCX/LaTeX sidecar 参数 | 修改 `pdf_variables`、`pdf_extra_args`、`latex_template_dir`、`docx_reference_doc` |
| 导出 profile 枚举 | `backend/app/schemas/enums.py` | `ExportProfile.CUMCM2026` | 一般不需要改 |
| 默认建模 profile | `backend/app/schemas/request.py` | `DEFAULT_MODELING_EXPORT_PROFILE = ExportProfile.CUMCM2026` | 一般不需要改 |
| API 默认值 | `backend/app/routers/modeling_router.py` | `/modeling` 默认 `cumcm2026` | 一般不需要改 |
| 主 PDF 导出 | `backend/app/tools/pdf_exporter.py` | Pandoc + XeLaTeX，主交付 PDF | 仅当官方要求 raw TeX、目录、特殊参数时调整 |
| DOCX reference | `backend/app/templates/export_profiles/cumcm2025_docx/format2025_reference.docx` | 当前 2026 暂时复用 2025 | 官方给 Word/DOCX 模板后新增 `cumcm2026_docx/format2026_reference.docx` 并切换 |
| 任务级模板覆盖 | 任务目录 `export_template_override.json`、`template_overrides/` | 仅对当前任务生效，DOCX/受限合同以 SHA-256 绑定；审计标记 `user_supplied_unverified` | 官方包尚未纳入仓库时优先用 `export_cli template install` + `task-refresh`，不得把覆盖写成官方认证 |
| LaTeX 模板资源 | 无外部 2026 类文件 | 当前 2026 sidecar 使用代码内无封面 `ctexart` 外壳，不复制 2025 `gmcmthesis` | 官方给 LaTeX 模板后新增 `cumcm2026/` 并切换 |
| LaTeX sidecar main 模板 | `backend/app/tools/tex_project_exporter.py` | `_CUMCM2026_MAIN_TEX_TEMPLATE`；无封面、无目录、无身份字段，`listings` 使用 `\ttfamily\footnotesize` 并自动换行 | 官方 LaTeX 模板结构变化时修改；保留 `% MMA_SECTION_INPUTS` 与代码换行/字号回归 |
| 论文后处理/预检 | `backend/app/tools/paper_postprocessor.py` | 参考文献、附录、支撑材料、路径、宽表、claim trace；默认附录 B 写入完整脚本/notebook 代码单元及 SHA-256 | 官方附录或提交规则变化时修改；同步更新 `complete_source_appendix` 验收与回归测试 |
| PDF 后验检查 | `backend/app/tools/pdf_visual_checker.py` | A4、非空、文本可提取、边缘溢出 | 官方尺寸/边距变化时调整 |
| 使用文档 | `STARTUP.md`、`docs/md/PDF模板导出说明.md` | 使用与验收入口 | 每次模板替换后同步更新 |

## 如果官方只发布 PDF 格式规范

- 不新增模板文件。
- 打开 `backend/app/tools/export_profiles.py`
- 修改 `CUMCM2026_PROFILE.pdf_variables`
  - `geometry`
  - `fontsize`
  - `pagestyle`
  - `PDF_HEADING_STYLE`
  - 是否保留 `pdf_extra_args=[]`
- 修改 `docs/md/PDF模板导出说明.md` 中的格式说明。
- 运行验证命令：

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py app/tests/test_paper_postprocessor.py
uv run python scripts/smoke_pdf_export.py
```

## 如果官方发布 Word/DOCX 模板

- 新建目录：
  `backend/app/templates/export_profiles/cumcm2026_docx/`
- 将官方 Word 模板转换或保存为：
  `backend/app/templates/export_profiles/cumcm2026_docx/format2026_reference.docx`
- 如果官方给的是 `.doc`，先用 LibreOffice 转成 `.docx`，命令示例：

```powershell
soffice --headless --convert-to docx --outdir backend\app\templates\export_profiles\cumcm2026_docx path\to\official_format2026.doc
```

- 修改 `backend/app/tools/export_profiles.py`：
  - 新增：
    `CUMCM2026_DOCX_REFERENCE = os.path.join(TEMPLATES_ROOT, "cumcm2026_docx", "format2026_reference.docx")`
  - 将 `CUMCM2026_PROFILE.docx_reference_doc` 从 `CUMCM2025_DOCX_REFERENCE` 改为 `CUMCM2026_DOCX_REFERENCE`
- 运行验证：

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py
uv run python -m app.tools.export_cli pdf --input examples\pdf_export_sample\res.md --output examples\pdf_export_sample\res.pdf --profile cumcm2026 --local
```

- 用一个真实任务检查：
  `res.docx`
  `res.pdf`
  `export_status.json`
  `candidate_manifest.json`

## 如果官方发布 LaTeX 模板

- 新建目录：
  `backend/app/templates/export_profiles/cumcm2026/`
- 放入官方 LaTeX 模板资源，例如：
  - `gmcmthesis.cls` 或官方 `.cls`
  - `main.tex`
  - `figures/`
  - `*.sty`
  - 其他官方资源
- 不要覆盖 `cumcm2025/`，保留历史模板。
- 修改 `backend/app/tools/export_profiles.py`：
  - 新增：
    `CUMCM2026_TEMPLATE_DIR = os.path.join(TEMPLATES_ROOT, "cumcm2026")`
- 将 `CUMCM2026_PROFILE.latex_template_dir` 从当前的 `None` 改为 `CUMCM2026_TEMPLATE_DIR`
- 修改 `backend/app/tools/tex_project_exporter.py`：
  - 根据官方 `main.tex` 更新 `_CUMCM2026_MAIN_TEX_TEMPLATE`
  - 保留 `% MMA_SECTION_INPUTS` 占位符
  - 确保生成的 `main.tex` 会 input `sections/*.tex`
  - 保留本地图片复制和 `copied_assets` / `missing_assets` 状态记录逻辑
  - 如果官方模板要求题号、队号、学校等信息，不要硬编码真实身份；需要保持空值或占位，避免论文泄露身份
- 验证：

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_tex_project_exporter.py app/tests/test_export_profiles.py
uv run python -m app.tools.export_cli latex --input examples\pdf_export_sample\res.md --work-dir examples\pdf_export_sample --profile cumcm2026
cd examples\pdf_export_sample\latex_project
xelatex -no-shell-escape -interaction=nonstopmode main.tex
xelatex -no-shell-escape -interaction=nonstopmode main.tex
```

## 比赛前 10 分钟快速定位清单

- [ ] 打开 `https://www.mcm.edu.cn/`
- [ ] 检查是否有新的 2026 格式规范、承诺书、编号页、DOCX 模板、LaTeX 模板
- [ ] 打开 `https://cumcm.cnki.net`
- [ ] 检查提交系统要求：论文格式、支撑材料格式、大小限制、是否只接受 PDF
- [ ] 如果没有新模板：继续使用当前 `cumcm2026`
- [ ] 如果有 Word/DOCX：按本指南替换 `cumcm2026_docx`
- [ ] 如果有 LaTeX：按本指南替换 `cumcm2026`
- [ ] 替换后必须跑：

```powershell
cd backend
uv run ruff check app
uv run python -m unittest app/tests/test_export_profiles.py app/tests/test_pdf_template_command.py app/tests/test_tex_project_exporter.py app/tests/test_paper_postprocessor.py
uv run python scripts/smoke_pdf_export.py
```

- [ ] 最后用真实题目或样例生成：
  `res.pdf`
  `res.docx`
  `paper_preflight_report.json`
  `pdf_visual_check.json`
  `candidate_manifest.json`
- [ ] 确认 `final_acceptance_report.json -> complete_source_appendix=PASS`，且未启用仅供阅读的 `mode=key`；再人工运行源码、核对正文结果与完整附录内容。不得以技术报告 `PASS` 替代数学、排版和平台规则复核。
