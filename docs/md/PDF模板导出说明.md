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
> - **`backend/app/tools/export_cli.py`**（推荐）：支持 `default`/`cumcm2025`
>   两种排版配置、字体检测+清晰的缺失提示、`--mainfont` 等参数手动覆盖字体、
>   以及导出 LaTeX sidecar 项目供手动编译。用法见 `STARTUP.md` 的
>   "Windows 本地 PDF 导出 / 手动编译"一节。
> - **`backend/scripts/export_pdf_local.py`**（本文档下方描述的脚本）：更早期的
>   task_id 驱动脚本，只支持默认参考排版（不感知 `cumcm2025` 等 profile），字体
>   名通过参数直接指定、没有自动检测/fallback，胜在读取 Docker 任务目录
>   （`backend/project/work_dir/<task_id>/`）更方便，适合"直接补一份默认排版
>   PDF"这种最简场景。

## 当前推荐流程

Docker 后端默认负责完成建模主流程，并生成：

- `res.md`
- `res.json`
- `res.docx`
- `candidate_manifest.json`
- 题目要求的中间结果文件，例如 `result1.xlsx`、`result2.xlsx`、`result3.xlsx`
- `res.pdf`（容器内 pandoc/xelatex 已装好，正常情况下会一并生成；字体是开源
  fallback 字体，仅用于自动化预览）

正式提交前，PDF 推荐在 Windows 本机用官方字体重新生成一份。推荐路径是：

```text
Docker 生成 res.md/res.docx（+ 自动化预览用的 res.pdf） ->
Windows 本机工具读取 res.md -> Pandoc + XeLaTeX 用真实系统字体重新生成 res.pdf
```

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

## 版式要求

默认 PDF 模板约定如下：

- A4 纸张。
- 首页直接为题目、摘要、关键词，不自动生成封面或目录页。
- 无页眉，页码使用页脚 plain 样式。
- 文档类为 `ctexart`。
- 中文正文字体为 `SimSun`。
- 中文标题/无衬线字体为 `SimHei`。
- 西文字体为 `Times New Roman`。
- 页边距为左/右 `3.17cm`，上/下 `2.6cm`。

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
如果确实没有，先看后端日志里 `tex_export_status.json`/PDF 相关的 `reason`
字段定位原因；如果只是想尽快补一份 PDF，可以直接在 Windows 本机运行：

```powershell
python backend\scripts\export_pdf_local.py <task_id>
```

或者用支持更多 profile/字体检测的新工具（见文首"更新"提示）：

```powershell
cd backend
uv run python -m app.tools.export_cli pdf --input project\work_dir\<task_id>\res.md --output project\work_dir\<task_id>\res.pdf --profile cumcm2025 --local
```

### 已经有 DOCX，为什么还用 Markdown 生成 PDF

项目当前模板参数是通过 Pandoc/XeLaTeX 控制的，输入是 `res.md`。这条路径比
`DOCX -> PDF` 更容易保持竞赛论文版式一致。`res.docx` 是 Word 交付文件，
`res.pdf` 是模板 PDF 交付文件，二者都来自同一份论文内容。

### 必须从 DOCX 转 PDF 怎么办

当前项目没有内置稳定的 `DOCX -> PDF` 后端能力。本机也未确认安装
LibreOffice / `soffice`。如必须走 DOCX 转 PDF，需要额外安装 LibreOffice
或使用 Word 自动化，并另行验证字体、页边距、目录和公式渲染是否符合模板。
