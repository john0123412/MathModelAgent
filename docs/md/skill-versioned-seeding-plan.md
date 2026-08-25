# 技能版本化播种方案设计（hashSkillDir + seeded-builtins.json）

> 状态：**设计文档，本轮不实现代码。**
> 依据：官方桌面版 v0.0.11 反编译产物 `extracted/app-src/out/main/index.js` 中的
> `hashSkillDir` 与技能播种循环；事实核验日期 2026-08-25。

## 一、要解决的问题

仓库 `skills/` 目录同时承担两个角色：

1. 本地开发的工作区——用户和 agent 会直接修改技能文件；
2. 将来分发的"出厂资产"——应用升级时需要把新版本技能铺到用户机器上。

直接整目录覆盖会吞掉用户的本地定制；只做增量又无法感知"哪些文件被改过"。
桌面版的解法是**版本化播种**：给每个技能目录算内容哈希，用一张种子表判断
"这个技能在用户机器上是原样、被改过、还是根本没装"。

## 二、桌面版机制还原（反编译结论）

```text
hashSkillDir(dir):
    h = sha256()
    walk(dir):                          # 递归遍历
        entries = sorted(by name, localeCompare)
        for entry in entries:
            rel = 相对路径（'/' 分隔）
            if entry 是目录: 递归(rel)
            else:             h.update(rel); h.update(文件内容)

播种循环（对每个内置技能 r）：
    src    = 应用资源里的原始技能目录
    hash   = hashSkillDir(src)
    dst    = 用户侧技能安装目录中同名目录
    seeded = 已加载的 seeded-builtins.json（name -> 上次播种哈希）

    if dst 存在:
        if seeded[r.name] == hash: continue      # 原样 → 不动（保留用户运行时产物）
        else:                      删除 dst 后整体复制   # 升级覆盖用户修改
    else:
        if r.name in seeded: continue            # 被用户主动删除 → 尊重
        复制 src -> dst
        if src 内存在 .disabled-by-default 标记: 安装为禁用态

    seeded[r.name] = hash                        # 更新种子表
持久化 seeded-builtins.json
```

关键语义：

- **哈希是"出厂内容指纹"而非"当前安装指纹"**：比对的是资源侧原始目录的哈希与
  种子表中记录的哈希，因此能区分"新版本"与"上次已铺过的旧版本"。
- **升级优先于本地修改**：只要出厂内容变了就整目录重铺，不做逐文件合并。
- **`.disabled-by-default` 是随包标记**：首次播种时决定该技能的默认启停状态，
  与本仓库 skills/data-search、skills/metaheuristic-optimization 的现有约定一致。
- **用户删除被尊重**：装过的名字仍在种子表里但目录没了 → 不复活。

## 三、本仓库适配方案（将来实现时的设计）

### 触发时机

- 分发场景：应用/插件启动时、或用户手动执行"修复技能"命令；
- 本地开发场景：不自动触发（开发者改动 skills/ 是常态），仅提供显式校验子命令。

### 建议实现形态

新增 `scripts/seed_skills.py`（纯标准库）+ 根目录或分发清单中的
`seeded-builtins.json`：

```text
seed_skills.py verify     # 只读：报告每个技能的 状态 ∈ {pristine, modified, missing, unseeded}
seed_skills.py repair     # 写操作：按桌面版语义重铺（必须先经用户确认）
seed_skills.py stamp      # 以当前工作区为准重建种子表（发版前执行）
```

### 与本仓库现状的衔接

| 现有约定 | 衔接方式 |
| --- | --- |
| `.disabled-by-default` 标记（data-search / metaheuristic-optimization） | 首次播种按标记决定启停，语义不变 |
| `skills/.claude-plugin/plugin.json` 插件清单 | 插件安装路径下同样适用本方案；种子表可放进插件清单同目录 |
| `skills.sh.json` | 若其登记了技能入口清单，播种范围以其为权威来源 |
| AGENT_MEMORY 中"多 worktree 并行"事实 | worktree 场景下每个树有独立工作副本，verify 必须以当前树为根（复用 doctor/check_env.py 的 REPO_ROOT 推导模式） |

### 冲突策略（与桌面版的一处刻意分歧）

桌面版选择"升级即覆盖"。本仓库的用户群体会深度定制模板（如
`5writing/templates/**`、`mathmodel-figure-templates/scripts/templates/**`），
建议在 repair 前增加一步：

1. 对将被覆盖的目录先做 `hashSkillDir` 快照并归档到
   `data/backups/skills-<timestamp>/`（或提示用户自行提交 git）；
2. 再执行重铺。

这样既保留桌面版"升级确定性"的优点，又不静默丢弃定制成果。

## 四、开放问题（实现前需决策）

1. 种子表的存放位置：跟随分发物（保证自洽）还是放用户配置目录（跨版本累计）？
   桌面版放在用户侧且随播种更新，建议沿用。
2. 大体积资产是否参与哈希：`4drawio/assets/icons/tabler/`（约百个 SVG）、
   `mathmodel-figure-templates/assets/previews/`（32MB）参与哈希会让每次启动
   校验变慢；可考虑对超阈值文件只哈希 `(path, size)`。
3. 与 Claude Code 插件更新机制的职责边界：若将来完全走插件市场分发，
   版本管理交给插件机制，本方案退化为"插件内的完整性校验工具"。
