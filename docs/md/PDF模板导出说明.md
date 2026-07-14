# PDF 模板导出说明

项目 PDF 导出以参考论文版式为目标，使用 Pandoc 调用 XeLaTeX 生成。

> **更新**：Docker 镜像现在已经装好 `pandoc`/`xelatex`/TeX Live（含中文字体包），
> 容器内可以直接生成 PDF/LaTeX sidecar，不再像早期版本那样默认跳过。容器内没有
> Times New Roman/SimSun 等官方 Windows 字体，会在编译期自动检测并 fallback 到
> 开源等效字体（Liberation Serif/Mono/Sans、Noto Serif/Sans CJK SC、AR PL
> KaitiM GB），用于**自动化预览**，足以保证任务不因为字体缺失而失败，但排版观感
> 和官方规范会有细微差异。
>
> 正式提交前，建议在已装有官方字体的 Windows 本机重新导出一次 PDF，本机默认会
> 优先使用真实系统字体。现在有两个本机导出工具：
>
> - **`backend/app/tools/export_cli.py`**（推荐）：支持 `default`/`cumcm2025`/
>   `cumcm2026`/`huashubei` 等排版配置；高教社杯/国赛（CUMCM）建议使用
>   `cumcm2026`，`huashubei` 仅用于华数杯。该工具支持字体检测+清晰的缺失提示、`--mainfont` 等参数手动覆盖字体、
>   以及导出 LaTeX sidecar 项目供手动编译。用法见 `STARTUP.md` 的
>   "Windows 本地 PDF 导出 / 手动编译"一节。
> - **`backend/scripts/export_pdf_local.py`**（本文档下方描述的脚本）：更早期的
>   task_id 驱动脚本，只支持默认参考排版（不感知 `cumcm2025`/`cumcm2026` 等 profile），字体
>   名通过参数直接指定、没有自动检测/fallback，胜在读取 Docker 任务目录
>   （`backend/project/work_dir/<task_id>/`）更方便，适合"直接补一份默认排版
>   PDF"这种最简场景。

## 当前推荐流程

Docker 后端默认负责完成建模主流程，并生成：

- `res.md`
- `res.json`
- `res.docx`
- `candidate_manifest.json`
- `paper_preflight_report.json/md`
- `paper_outline.json`
- `figure_usage.json`
- `claim_trace.json/md`
- 题目要求的中间结果文件，例如 `result1.xlsx`、`result2.xlsx`、`result3.xlsx`
- `res.pdf`（容器内 pandoc/xelatex 已装好，正常情况下会一并生成；字体是开源
  fallback 字体，仅用于自动化预览）
- `latex_project/`（候选 LaTeX sidecar；`main.tex` 输入结构化 `sections/*.tex`，
  并保留 `sections/imported_body.tex` 作为兼容审计文件；编译失败只记录到
  `tex_export_status.json`，不阻断主交付链路；导出器会复制正文引用的本地图片到
  `latex_project/` / `latex_project/figures/`，并记录 `copied_assets` /
  `missing_assets`；若图片文件名包含 `%`、中文、`±` 等 LaTeX 高风险字符，
  sidecar 内部会改用 `figures/figure_XX.ext` 安全文件名并重写 `sections/*.tex`
  的 `\includegraphics` 引用，不改变 `res.md`、`res.pdf`、`res.docx`）

正式提交前，PDF 推荐在 Windows 本机用官方字体重新生成一份。推荐路径是：

```text
Docker 生成 res.md/res.docx（+ 自动化预览用的 res.pdf） ->
Windows 本机工具读取 res.md -> Pandoc + XeLaTeX 用真实系统字体重新生成 res.pdf
```

标准化依据：官方 2026 论文格式规范页面
`https://www.mcm.edu.cn/html_cn/node/4cd596519c9eb9fbd866398f6df0caa3.html`
要求电子版论文为单独 PDF/Word 文件（建议 PDF、≤20MB），第一页为摘要页，
不放承诺书和编号专用页；电子版应与纸质版内容和格式一致，论文附录应包含全部完整、可运行
源程序；支撑材料另行提交，也至少包含必要源程序、数据资料和较大篇幅中间结果图表。

> **完整源码与最终验收**：后处理现在会在附录 B 写入任务目录发现的完整可运行脚本及 notebook
> 代码单元（不含 notebook 运行输出），并在每份源码标题记录原始 SHA-256。DOCX 生成并刷新
> manifest 后会生成 `final_acceptance_report.json/md`：只有执行验证、冻结来源、预检、PDF 视觉、
> 正式字体、主交付文件和完整源码附录均通过时才为 `TECHNICAL_PASS`。该状态仍不替代数学、引用、
> PDF 人工翻阅及平台规则的人工复核，报告会始终标注 `PENDING_HUMAN_REVIEW`。

> **TeX Live 本机复核边界**：已安装 TeX Live 的 Windows 主机可在执行验证、冻结和正文预检均通过后，
> 用 `export_cli pdf --local --update-status` 或导出的 `latex_project/` 进行正式字体 PDF 复核。
> TeX 编译只验证排版和字体，不能把 `execution_validation_report.json = FAIL` 的任务变为可验收论文。

## 高教社杯 `cumcm2026` 验收要点

当前官方可见附件是 2026 论文格式规范 PDF；项目内没有官方 2026 DOCX/LaTeX
源模板，`cumcm2026` 是按修订稿规范实现的暂定模板。正式比赛前必须重新检查
官方站和知网提交系统；如果新增 Word/DOCX 或 LaTeX 模板，按
`docs/md/CUMCM2026模板替换指南.md` 替换。

已归档的 E2B 真实轻量线性规划任务 `20260711-133616-38439fe3` 使用
OpenAI Responses 兼容运行配置和 `export_profile=cumcm2026`，通过下列主交付与严格字体验收：

- `paper_preflight_report.json`：`PASS`
- `pdf_visual_check.json`：`PASS`，A4、非空、文本可提取、20MB 文件大小、摘要首页、
  无目录、正文 30 页以内、匿名电子稿身份字段、物理边缘越界和 CUMCM 2.5cm 内容边距检查均通过
- `res.md`、`res.pdf`、`res.docx`、`res.json`、`candidate_manifest.json` 均生成
- `tex_export_status.json`：`compile_success=true`，`missing_assets=[]`
- `latex_project/main.pdf` 已生成且非空
- `submission_audit --require-official-fonts`：`PASS`；实际 PDF 字体命中
  `SimSun`、`SimHei`、`Times New Roman`
- 真实产物包含 PNG 图片、CSV 表格数据和 `notebook.ipynb` 源码附录
- 人工数值复核：最优方案 `A=40`、`B=20`、利润 `2200`；机器时间增加 10 小时后
  利润约为 `2366.67`
- 本次复核确认 `pdf_visual_check.json -> checks.abstract_first_page` 通过，第一页只包含
  标题、摘要和关键词，不再混入正文“问题重述”。
- 最新一次真实恢复验收为 `20260713-021852-8d8e948a7a679b5abcd5e76d25894412`：在可信单用户
  Docker 本地执行覆盖中从 checkpoint 续传，主产物、preflight、PDF visual check、submission
  audit 和 LaTeX sidecar 均成功。该次只验证受控恢复与技术导出链路，**不**验证远程 E2B、
  正式字体或“论文附录含全部源码”的正式提交要求。
- Docker 中官方 Windows 字体缺失时，`SimSun/SimHei/Times New Roman` 会 fallback 到
  `Noto Serif CJK SC`、`Noto Sans CJK SC`、`Liberation Serif`；CUMCM sidecar 中
  `KaiTi` / `STXinwei` / `LiSu` 会优先 fallback 到 `AR PL KaitiM GB`，若仍缺失则
  fallback 到 Noto CJK 字体。正式提交前仍建议挂载宿主机合法安装的正式字体，或在
  Windows 本机用真实字体重新导出。
- Docker 不能把开源字体“转换”为专有正式字体。自动化路径是设置根目录 `.env`：
  `MMA_OFFICIAL_FONTS_DIR=C:\Windows\Fonts`，Compose 会把该目录只读挂载到
  `/usr/local/share/fonts/mma-extra`，后端入口自动刷新 `fc-cache`。随后
  `fc-match "SimSun"`、`fc-match "Times New Roman"` 命中正式字体时，
  Docker PDF 会直接使用正式字体，不再触发对应 fallback。
- 任务完成后会生成 `submission_audit_report.json/md`；默认模式下 Docker fallback
  字体记为 `WARN`；`paper_preflight_report.json = CONDITIONAL_PASS` 也会记为
  `WARN`，表示主交付可生成但存在需人工接受或修正的条件项。正式提交前可运行
  `uv run python -m app.tools.submission_audit --work-dir project\work_dir\<task_id> --require-official-fonts`
  作为严格门禁，若 PDF 仍有 fallback/未知字体来源则返回 `FAIL`。

`cumcm2026` 主 PDF 和 LaTeX sidecar 都显式关闭 pandoc raw TeX，并支持 `\( ... \)` 内联数学；
附录代码会防止源码中的 `\end{lstlisting}` 提前结束 LaTeX 代码环境，避免 notebook
里嵌套的 LaTeX 模板字符串把 `\begin{table}[H]` 等内容泄漏成正文 LaTeX，从而造成
PDF 编译失败或代码越界。

PDF/sidecar 自动编译会显式禁用 XeLaTeX shell escape；模型或 Markdown 中的 `\input`、
`\write18` 等 raw TeX 命令不会透传到候选工程。手动复编也应带
`-no-shell-escape`。

`cumcm2026` 主 PDF 页边距当前使用 `left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm`。
底边距高于规范最低 2.5cm，是为了给实际字体字形 bbox 留出安全余量，避免正文末行
侵入 CUMCM 2.5cm 内容边距保护区。

需要注意的边界：

- 新建 `/modeling` 任务默认使用 `cumcm2026`；脚本、curl 或旧客户端仍建议显式传
  `export_profile=cumcm2026`，便于复核。
- `cumcm2026` 当前复用 2025 年 LaTeX 模板资源目录和 DOCX reference-doc；2026
  正式模板发布后应重新复核。
- `latex_project/` 是候选 sidecar，不是主交付链路；导出器会尽量自动编译，
  但若失败只写入 `tex_export_status.json`，不影响 `res.md`/`res.pdf`/`res.docx`
  主交付。若要把它作为正式可编译工程交付，需要单独复核 `main.pdf` 和编译日志。
- `pdf_visual_check.json` 是低成本自动检查；它会检查 A4、非空、文本可提取、
  20MB 文件大小、摘要首页、无目录、正文 30 页以内、物理边缘越界和 CUMCM
  2.5cm 内容边距风险（允许少量字形 bbox 容差），并阻断 `承诺书`、`编号专用页`、
  `参赛队号` 等匿名电子稿不应出现的身份/封面字段，但仍不替代人工翻阅 PDF。
- raw TeX 已在主 PDF 与 LaTeX sidecar 导出中关闭，正文不要依赖 `\begin{table}`、`\begin{align}`
  等 raw LaTeX 环境；标准 Markdown 表格与 `$...$`、`\(...\)` 数学公式仍可用。
- `paper_preflight_report.json` 只说明格式门禁和基本证据链通过，不证明数学模型和论文论证正确。
  对冻结结果与正文不一致这类可明确定位到 `quesN`/摘要的硬失败，工作流只允许一次定向 Writer
  回修并重新预检；无法定位或回修后仍为 `FAIL` 时不会继续生成候选 PDF。该机制只修复可追溯的
  文本事实冲突，不能替代人工复算或把不完整的模型结论“润色”为通过。
  预检会额外检查正文引用编号是否都有文末参考文献条目、Markdown 表格是否有
  `表n` 标题、以及两问任务中是否把扩展灵敏度分析误标为可见的 `问题3` 或
  `问题三` 段落。工作流会把原题拆出的正式题目数传入后处理，避免 Writer 自行编出
  的额外问题影响判断。
- 后处理会在参考文献条目之间保留空行，避免 Pandoc 导出 PDF/DOCX 时把多条文献
  合并为同一段；若模型生成空参考文献段且正文没有有效引用，后处理会删除空参考文献段，
  预检不再因为“无引用且无文献”单独失败，但人工复核仍需确认需要引用的背景或方法是否有真实来源。
- 后处理会删除孤立的 `: ... DOI ...` 定义式参考行，避免 Pandoc 将前一整段正文
  误解析成 LaTeX description label，导致 PDF 正文无法正常换行。
- 无外部数据集的题目不应为了 EDA 随机生成模拟样本或模拟数据集；这类题目的“数据预处理”
  应聚焦题目参数、单位、约束和可行域核验。只有真实存在外部数据集时，才做缺失值、异常值、
  分布可视化等数据驱动 EDA。若正文已经说明题目参数是确定性常量、无随机样本数据，
  后处理会把 `描述性统计` 这类样本数据 EDA 用语规范为 `参数核验`，并清理正文、
  图片引用和支撑材料表中的 Monte Carlo/蒙特卡洛/随机模拟内容；代码附录中同类标签会
  降级为参数扰动表述，避免确定性题正式稿混入探索性随机模拟口径。
- 后处理会清洗 Markdown 图片 alt 文本，避免 Pandoc 生成的 PDF/DOCX 图题直接带
  `.png`、下划线或空 alt 等文件名痕迹；只调整图题文本，不改变图片路径。
- 后处理会把正文中的常见英文过渡词（如 `Overall`、`However`、`In addition`）
  替换为中文表达，避免中文竞赛论文中出现突兀英文衔接词；代码块内容不处理。
- 后处理会清理最终稿和附录代码中可见的提交痕迹词，例如 `用户`、`推断`、
  `估算`、`待验证`，改为 `题目`、`核定`、`测算`、`需核验` 等正式表达。
- 后处理会重建附录；附录 B 保留全部发现的可运行源码，并为每份源码写入 SHA-256。
  不再截断为核心代码摘录，也不删除源码中的有效 `print(...)` 等语句。notebook 只导出代码
  单元，不导出运行输出。`final_acceptance_report.json -> complete_source_appendix` 会同时核对
  源码标题哈希与正文中的完整代码内容，不能只凭附录 A 文件清单通过。
- 附录外的装饰性超长代码分隔线仍会缩短；完整源码附录不做截断。若完整源码导致 PDF 页数、
  边距或安全转义问题，应先模块化/清理源码并重新导出，不能用“以下代码略”冒充完整附录。
- 如需按国一复刻模板的阅读方式展示算法，可由受控导出流程在任务目录设置
  `paper_appendix_config.json` 为 `{"mode":"key"}`，并提供已验证的 `key_algorithms.md`：
  其中只放关键伪代码和核心实现，不能放控制台输出、绝对路径或未执行的示例。此模式的完整源码
  仍属于支撑材料，`final_acceptance_report.json` 会因 `complete_source_appendix` 不通过而保持
  非 `TECHNICAL_PASS`；正式提交必须移除该配置或改回 `full`，让附录 B 包含全部完整可运行源码。
- 后处理会把独占一行的加粗短标签（如 `**假设1：...**`）规范为 Markdown 小标题，
  避免后续段落被 Pandoc 误当成不可换行的 definition-list 标签。

注意：当前模板 PDF 不是从 `res.docx` 转换而来，而是从 `res.md` 直接生成。
这样可以稳定控制论文模板参数，例如 `ctexart`、中文字体、A4 纸张、页边距、
页脚页码和是否生成目录页。若强行走 `DOCX -> PDF`，通常需要 LibreOffice
或 Microsoft Word 自动化，版式一致性反而更难保证。

## 运行环境

本机需要可在 `PATH` 中找到：

```powershell
pandoc
xelatex
```

当前 Windows 本机可用路径示例：

```text
D:\Scoop\shims\pandoc.exe
D:\texlive\2026\bin\windows\xelatex.exe
```

Docker 后端镜像现在默认已安装 Pandoc / TeX Live（含 `fonts-liberation`/
`fonts-noto-cjk` 等开源字体作为 fallback）。极端情况下容器环境异常导致工具
缺失时，主流程会跳过 PDF，但仍会生成 `res.md`、`res.json`、`res.docx` 和
`candidate_manifest.json`。

## 版式要求（按 export profile 区分）

新建建模任务默认使用 `cumcm2026`，其主 PDF 约定如下：

- A4 纸张。
- 第一页直接为题目、摘要、关键词，摘要页独占第一页；正文从第二页开始。
  该分页是 PDF-only 预处理，不写回 `res.md`，也不影响 DOCX 或 LaTeX sidecar。
  分页识别支持裸 `关键词：...` 和加粗内联 `**关键词**：...`。
- PDF-only 预处理还会给连续中文长句插入内部断行标记，再由 Lua filter 转为
  LaTeX 断点；该处理不回写 `res.md`，也不影响 DOCX 或 LaTeX sidecar。
- 不自动生成封面或目录页。
- 无页眉，页码使用页脚 plain 样式。
- 文档类为 `ctexart`。
- 中文正文字体为 `SimSun`。
- 中文标题/无衬线字体为 `SimHei`。
- 西文字体为 `Times New Roman`。
- 页边距为左/右 `3.17cm`、上 `3cm`、下 `2.8cm`。

历史兼容的 `default` profile 才使用上/下 `2.6cm`；较早的
`backend/scripts/export_pdf_local.py` 也是仅支持该默认参考排版的旧脚本。高教社杯/国赛应使用
下文的 `app.tools.export_cli --profile cumcm2026`，不要把旧脚本的边距或目录选项当作
`cumcm2026` 的正式口径。

## 导出方式

已完成任务可以用本机脚本补生成 PDF：

```powershell
cd D:\workspace\MathModelAgent
python backend\scripts\export_pdf_local.py <task_id>
```

示例：

```powershell
cd D:\workspace\MathModelAgent
python backend\scripts\export_pdf_local.py 20260703-110744-8d9de030
```

如需显式指定工具路径：

```powershell
python backend\scripts\export_pdf_local.py <task_id> --pandoc D:\Scoop\shims\pandoc.exe --xelatex D:\texlive\2026\bin\windows\xelatex.exe
```

默认不生成目录页；只有明确需要目录页时才加：

```powershell
python backend\scripts\export_pdf_local.py <task_id> --toc
```

生成成功后会写入：

- `backend/project/work_dir/<task_id>/res.pdf`
- `backend/project/work_dir/<task_id>/export_status.json`

如果存在 `candidate_manifest.json`，脚本会把 `files.res_pdf` 更新为 `res.pdf`。

## 生成后检查

生成成功后建议检查以下文件：

```powershell
cd D:\workspace\MathModelAgent
Get-Item backend\project\work_dir\<task_id>\res.pdf
Get-Content backend\project\work_dir\<task_id>\export_status.json -Raw
Get-Content backend\project\work_dir\<task_id>\candidate_manifest.json -Raw
```

如果本机有 `pdfinfo`，可检查页数和纸张：

```powershell
D:\texlive\2026\bin\windows\pdfinfo.exe backend\project\work_dir\<task_id>\res.pdf
```

关键检查项：

- `Pages` 应大于 0。
- `Page size` 应为 A4，通常显示为 `595.28 x 841.89 pts`。
- `Creator` 应显示 `LaTeX via pandoc` 或类似信息。
- `candidate_manifest.json` 中 `files.res_pdf` 应为 `res.pdf`。
- `pdf_visual_check.json` 应为 `PASS`，尤其是
  `checks.abstract_first_page.passed=true`、
  `checks.no_table_of_contents.passed=true`、
  `checks.submission_anonymity.passed=true`、
  `checks.body_page_limit.passed=true`、
  `checks.content_margin.passed=true`、
  `checks.text_margin.passed=true`。
- `submission_audit_report.json` 默认应为 `PASS` 或 `WARN`；`WARN` 可能来自
  Docker 字体 fallback 或 `paper_preflight_report.json = CONDITIONAL_PASS`，需查看
  具体检查项后人工接受或修正。若正式提交要求官方字体，
  运行 `python -m app.tools.submission_audit --work-dir <task_dir> --require-official-fonts`
  后应为 `PASS`。若为 `FAIL`，先按报告里的 remediation 挂载正式字体或本机重导。
- `paper_preflight_report.json -> checks.appendix_console_noise.passed` 应为 `true`。
  若失败，先重跑 `prepare_paper_markdown` 重建附录，再重导 DOCX/PDF。
- `paper_preflight_report.json -> checks.images.unused_generated` 应为空。若生成图片只作为
  支撑材料而不插入正文，必须出现在附录A支撑材料表中并标记为 `图片文件`；否则应删除、
  插入正文引用，或人工接受 `CONDITIONAL_PASS`。
- 可用 PyMuPDF 或其他 PDF 文本提取工具确认 `res.pdf` 中没有 `print(`、`printf`、
  `console.log` 等控制台输出痕迹。
- `tex_export_status.json` 中 `main_uses_structured_sections=true` 时，`latex_project/main.tex`
  应输入 `sections/00_*.tex`、`sections/01_*.tex` 等结构化章节。
- `tex_export_status.json` 中 `copied_assets` 会列出复制到 `latex_project/` 和
  `latex_project/figures/` 的本地图片；`missing_assets` 应为空。若不为空，应先修正
  `res.md` / `sections/*.tex` 中不存在的图片引用。若原始图片名含 LaTeX 高风险字符，
  `copied_assets` 中可能出现 `figures/figure_XX.ext`，这是 sidecar 为保证可编译
  生成的安全副本。
- `tex_export_status.json` 中 `compile_attempted=true` 时，重点看 `compile_success`、
  `compile_reason`、`compile_failure_summary`。当前自动编译优先尝试 `latexmk -xelatex`，
  并向 XeLaTeX 传入 `-no-shell-escape`，失败后会 fallback 到连续两次同样禁用 shell
  escape 的 `xelatex`；如果 `compile_success=false`，该失败仍是
  sidecar 风险，不代表主 PDF/DOCX 导出失败。

如需视觉检查前几页，可渲染为 PNG：

```powershell
New-Item -ItemType Directory -Force -Path .agent-work\screenshots\pdf-check | Out-Null
D:\texlive\2026\bin\windows\pdftoppm.exe -png -f 1 -l 3 -r 120 `
  backend\project\work_dir\<task_id>\res.pdf `
  .agent-work\screenshots\pdf-check\page
```

然后打开 `.agent-work/screenshots/pdf-check/page-01.png` 等图片，检查标题、
中文字体、页边距、页脚页码、表格和公式是否正常。

## Docker 与 BAT 启动说明

Docker Compose 服务和 `win_start.bat` 是两条不同启动路径：

- Docker Compose 后端默认使用 `http://127.0.0.1:8000`。
- Docker Compose 前端默认使用 `http://127.0.0.1:5173`。
- `win_start.bat` 会尝试启动本机后端 `http://127.0.0.1:8003`。
- `win_start.bat` 还会执行本机 `pnpm run dev` 启动前端。

当前 Windows 本机环境曾出现前端 Node 工具链异常派生大量 `node.exe` /
`cmd.exe` 的问题。因此 agent 不应自动运行 `win_start.bat`、`pnpm run dev`
或任何本机前端 Node 命令。需要使用 BAT 时建议由人工在确认 Node 环境健康后
手动运行。

`win_start.bat` 不能保证自动生成模板 PDF。它是否能生成 PDF 取决于：

1. 后端进程能否在 PATH 中找到 `pandoc`。
2. 后端进程能否在 PATH 中找到 `xelatex`。
3. 任务完成时是否生成了 `res.md`。

如果上述条件满足，本机后端可以按同一套 Pandoc/XeLaTeX 参数生成 `res.pdf`。
如果条件不满足，仍可在任务完成后使用 `backend\scripts\export_pdf_local.py`
手动补生成 PDF。

## 常见问题

### Docker 已完成任务但没有 PDF

Docker 镜像现在默认装有 Pandoc/TeX Live，正常情况下应该会生成 `res.pdf`。
如果确实没有，先看后端日志里 PDF 相关的 `reason` 字段定位原因；LaTeX sidecar
单独看 `tex_export_status.json` 的 `compile_reason` / `compile_failure_summary`。
如果只是想尽快补一份 PDF，可以直接在 Windows 本机运行：

```powershell
python backend\scripts\export_pdf_local.py <task_id>
```

或者用支持更多 profile/字体检测的新工具（见文首"更新"提示）：

```powershell
cd backend
uv run python -m app.tools.export_cli pdf --input project\work_dir\<task_id>\res.md --output project\work_dir\<task_id>\res.pdf --profile cumcm2026 --local --update-status
```

`--update-status` 会同步刷新 `export_status.json`、`pdf_visual_check.json`、
`submission_audit_report.json` 和已有的 `candidate_manifest.json`，避免正式字体
重导后审核仍引用旧的 Docker fallback 记录。

### 已经有 DOCX，为什么还用 Markdown 生成 PDF

项目当前模板参数是通过 Pandoc/XeLaTeX 控制的，输入是 `res.md`。这条路径比
`DOCX -> PDF` 更容易保持竞赛论文版式一致。`res.docx` 是 Word 交付文件，
`res.pdf` 是模板 PDF 交付文件，二者都来自同一份论文内容。

### 必须从 DOCX 转 PDF 怎么办

当前项目没有内置稳定的 `DOCX -> PDF` 后端能力。本机也未确认安装
LibreOffice / `soffice`。如必须走 DOCX 转 PDF，需要额外安装 LibreOffice
或使用 Word 自动化，并另行验证字体、页边距、目录和公式渲染是否符合模板。

## P0-P2 新鲜度、全页检查与内容表达规则（2026-07）

1. **新鲜度**
   - `export_status.json` 记录 PDF 的 `source_sha256` / `output_sha256`；`docx_export_status.json` 对 DOCX 记录同类字段。
   - 重导开始前先删除旧 `res.pdf` / `res.docx`。导出失败时不得继续把旧文件当成当前候选。
   - `submission_audit_report.json` 会核对当前 Markdown、PDF 与预检/视觉报告的哈希；`final_acceptance_report.json` 还会核对 manifest 中的主产物哈希。

2. **视觉覆盖**
   - `pdf_visual_check.json` 默认全页扫描，正式验收要求 `scan_scope=all_pages` 且 `pages_checked=page_count`。
   - 检查包括 A4、非空页、文本可提取、边距、匿名、目录禁用、正文 Markdown 表格源码泄漏等；通过后仍须人工逐页看图题、分页、公式和附录代码。

3. **结构与正文闭环**
   - 重复参考文献章节、孤立 `[n]` 片段、非法 pipe table、表题与表格之间缺空行属于硬失败。
   - 正文图片必须在正文中以“图N”引用；缺失时为 `CONDITIONAL_PASS`，不自动猜测应插入的语义句。
   - 已声明连续变量或允许小数解时，`46.67件` 等表达会触发 `continuous_quantity_wording` 条件项。推荐写作“46.67个连续生产当量”，并在实施边界中另报整数规划结果。

4. **附录代码版式**
   - PDF/LaTeX sidecar 的代码块使用 `\ttfamily\footnotesize`，目的是减少仅有一两行代码的孤立尾页，同时保留可读性。
   - 附录仍必须保留完整可运行代码、源码 SHA-256、必要断言和输出文件生成逻辑；缩小字体不能替代代码完整性检查。

5. **候选包**
   - `candidate_manifest.json` schema `1.1` 写入 `artifact_set_id` 与 `artifact_hashes`。
   - `recovery_review_pages/`、`failed_attempts/`、`.ipython/`、`.jupyter_runtime/`、`.matplotlib/`、`latex_project/` 等内部或 sidecar 目录不作为正式图表候选。
