# Export Profile Template Resources

- `cumcm2025/`: 2025 LaTeX sidecar 模板资源，仅供 `cumcm2025` 使用。
  `gmcmthesis.cls` 已加入容器友好的中文字体 fallback，`KaiTi` / `STXinwei` /
  `LiSu` 不存在时会回退到 `AR PL KaitiM GB` 或 Noto CJK 字体，优先保证候选
  LaTeX sidecar 可编译。
- `cumcm2025_docx/`: 2025 DOCX reference，目前被 `cumcm2026` 暂时复用。
- `cumcm2026` LaTeX sidecar 当前使用代码内的无封面 `ctexart` 外壳，而非
  `gmcmthesis`：2025 类的 `\maketitle` 会生成含学校、队号、队员字段的旧式封面，
  不符合 2026 电子版“摘要页为第一页、不得放承诺书和编号专用页”的要求。
- 如果官方发布 2026 Word/DOCX 模板，应新增：
  `cumcm2026_docx/format2026_reference.docx`
- 如果官方发布 2026 LaTeX 模板，应新增：
  `cumcm2026/`
- 不要覆盖 2025 目录，避免破坏历史 profile。
