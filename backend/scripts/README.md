# Backend Scripts

## Reference-Style PDF Export

> **Update**: the Docker backend image now ships `pandoc`/`xelatex`/TeX Live
> by default, so containers no longer skip PDF/LaTeX sidecar generation for
> lack of tooling. Container-side output uses open-source fallback fonts
> (Liberation Serif/Mono/Sans, Noto Serif/Sans CJK SC, AR PL KaitiM GB) when
> the official Windows fonts (Times New Roman/SimSun/etc.) aren't installed
> in the image — good enough for automated preview, but before a real
> submission you should regenerate the PDF on a Windows machine that has the
> real fonts. Two local tools are available now:
>
> - **`backend/app/tools/export_cli.py`** (recommended): supports
>   `default`/`cumcm2025`/`cumcm2026`/`huashubei` layouts. Use
>   `cumcm2026` for 高教社杯/CUMCM work; `huashubei` is only for 华数杯.
>   It detects installed fonts with clear warnings on fallback, lets you
>   override fonts (`--mainfont` etc.), and can export the LaTeX sidecar project for manual compilation.
>   The sidecar keeps `sections/imported_body.tex` for compatibility and now
>   writes structured `sections/*.tex` files that `main.tex` inputs by default. See
>   `STARTUP.md`'s "Windows 本地 PDF 导出 / 手动编译" section.
> - **`backend/scripts/export_pdf_local.py`** (described below): the earlier
>   task_id-driven script. Only produces the default reference layout (no
>   `cumcm2025`/`cumcm2026` awareness), font names are plain CLI arguments with no
>   detection/fallback, but it's convenient when you just want to point at a
>   Docker task directory (`backend/project/work_dir/<task_id>/`) and get a
>   default-layout PDF with minimal fuss.

> **CUMCM 2026 submission boundary**: the current automatic Appendix B keeps only
> concise code excerpts; complete runnable notebooks/scripts remain support material.
> The generated PDF and its technical audit are therefore candidate output, not proof
> that the official requirement for complete runnable source in the paper appendix has
> been met. Add the complete source to the appendix manually, or extend and verify the
> export pipeline before formal submission.

Use the host machine's Pandoc and TeX Live to generate a PDF for a completed
task without installing heavy TeX dependencies inside Docker:

```powershell
python backend\scripts\export_pdf_local.py <task_id>
```

The script reads `backend\project\work_dir\<task_id>\res.md` and writes
`res.pdf` plus `export_status.json` in the same task directory. If
`candidate_manifest.json` exists, `files.res_pdf` is updated to `res.pdf`.

The default export follows the reference paper layout:

- A4 page size.
- No generated cover page and no generated table of contents.
- No running page header; page numbers use the plain footer style.
- `ctexart` document class with Chinese scheme enabled.
- Chinese body font: `SimSun`.
- Chinese sans/title font: `SimHei`.
- Western font: `Times New Roman`.
- Margins: left/right `3.17cm`, top/bottom `2.6cm`.

This remains a handy path for a quick default-layout PDF from a Docker task
directory, or as a fallback if the container-side PDF is missing for any
reason. For 高教社杯/CUMCM `cumcm2026` output, older `cumcm2025` output, font
detection/fallback reporting, or a manual-compile LaTeX sidecar workflow, use
`app.tools.export_cli` instead (see the update note above).

When `HUMAN_MODEL_GATE_ENABLED=true`, Docker/Web tasks stop after Modeler and
write `modeling_decision.json/md` plus `checkpoint.json`. Confirm with
`POST /modeling/<task_id>/approve-modeling` to resume from Coder without
rerunning Coordinator/Modeler.

Useful options:

```powershell
python backend\scripts\export_pdf_local.py <task_id> --toc-depth 2
python backend\scripts\export_pdf_local.py <task_id> --toc
python backend\scripts\export_pdf_local.py <task_id> --timeout 600
python backend\scripts\export_pdf_local.py <task_id> --pandoc D:\Scoop\shims\pandoc.exe --xelatex D:\texlive\2026\bin\windows\xelatex.exe
```

Use `--toc` only when a generated directory page is explicitly needed. The
reference-style output keeps the first page as title, abstract, and keywords.

## End-to-End Usage

After a Docker task completes, the task directory should usually contain:

- `res.md`
- `res.json`
- `res.docx`
- `candidate_manifest.json`
- any requested result spreadsheets such as `result1.xlsx`, `result2.xlsx`, and
  `result3.xlsx`

Generate the reference-style PDF from the task Markdown:

```powershell
cd D:\workspace\MathModelAgent
python backend\scripts\export_pdf_local.py <task_id>
```

Example:

```powershell
python backend\scripts\export_pdf_local.py 20260703-110744-8d9de030
```

Successful output writes:

- `backend\project\work_dir\<task_id>\res.pdf`
- `backend\project\work_dir\<task_id>\export_status.json`

If `candidate_manifest.json` already exists, the script updates
`files.res_pdf` to `res.pdf`.

## Verification

Check the PDF metadata:

```powershell
D:\texlive\2026\bin\windows\pdfinfo.exe backend\project\work_dir\<task_id>\res.pdf
```

Expected high-level output:

- `Pages` is greater than zero.
- `Page size` is A4, normally `595.28 x 841.89 pts`.
- `Creator` is `LaTeX via pandoc` or equivalent.

Render the first pages for visual inspection:

```powershell
New-Item -ItemType Directory -Force -Path .agent-work\screenshots\pdf-check | Out-Null
D:\texlive\2026\bin\windows\pdftoppm.exe -png -f 1 -l 3 -r 120 `
  backend\project\work_dir\<task_id>\res.pdf `
  .agent-work\screenshots\pdf-check\page
```

Inspect the generated PNGs for readable Chinese text, sane margins, centered
headings, and footer page numbers.

## Markdown-to-PDF vs DOCX-to-PDF

This script intentionally uses `res.md` as input, not `res.docx`.

The reference layout is encoded in the Pandoc/XeLaTeX command:

- `documentclass=ctexart`
- `CJKmainfont=SimSun`
- `CJKsansfont=SimHei`
- `mainfont=Times New Roman`
- `geometry:left=3.17cm,right=3.17cm,top=2.6cm,bottom=2.6cm`
- no generated cover page
- no generated table of contents unless `--toc` is passed

Converting `res.docx` to PDF would require another renderer such as
LibreOffice or Word automation. That path is not the current supported backend
flow and must be separately validated for fonts, margins, equations, and tables.

## Windows BAT Launcher Notes

`win_start.bat` is a manual local launcher. It is separate from Docker Compose.

Important behavior:

- It kills processes listening on ports `8000`, `8001`, `8002`, `8003`, and
  `5173`.
- It starts Redis in Docker as `redis-mma`.
- It starts a local backend on port `8003`.
- It starts the local frontend with `pnpm run dev` on port `5173`.

Do not run this BAT from automation in the current Windows environment unless
the user explicitly accepts the risk. This project has seen local frontend Node
tooling spawn excessive `node.exe` processes. Prefer Docker Compose for normal
agent verification:

```powershell
docker compose up --build -d
curl.exe http://127.0.0.1:5173/api/docs
curl.exe http://127.0.0.1:5173/
```

The BAT launcher does not by itself provide DOCX-to-PDF conversion. The local
backend can generate PDF only when its process can find `pandoc` and `xelatex`
and the task has `res.md`. If PDF is missing after a BAT-run task, use:

```powershell
python backend\scripts\export_pdf_local.py <task_id>
```
