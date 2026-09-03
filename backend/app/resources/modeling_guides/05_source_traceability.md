# 数据与文献来源追溯（0.0.15 提炼，批 D）

**原则**：每个数值/引用必须可追溯至来源文件与哈希。

**何时加载**：所有题型的 Writer 与 Coder 阶段。

**执行清单**：
- 数据文件：`input_manifest.json` 登记 `name/relative_path/size_bytes/sha256`，`expected_artifacts` 的每个结果表须在 `frozen_results.json` 登记 `source.sha256`。
- 文献：先 `paper_search` 检索→`verify` 核对→`bib --doi` 生成，禁止手写题名/作者/卷期；正文每处引用须在 `paper_assets_manifest` 绑定断言位置与文献条目。
- 核验状态分档：`verified` / `not_accessible` / `doi_not_found` / `mismatch`，暂不可访问不等于伪造。

**门禁**：`source.sha256` 缺失或哈希不一致即 FAIL；引用无 DOI 或 DOI 核验失败且未标记 `mismatch` 即 WARN。
