# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MathModelAgent 是数学建模竞赛自动化系统，通过多 Agent 协作完成建模、代码生成和论文撰写。核心工作流：CoordinatorAgent 分析问题 → ModelerAgent 建模 → CoderAgent 编码执行 → WriterAgent 撰写论文。

## Commands

### 重要限制：Windows 本机前端 Node 命令

不要在本机 Windows 环境中主动运行前端依赖安装、构建、类型检查或 lint 命令，例如 `pnpm i`、`pnpm run build`、`vue-tsc`、`vite build`、`biome`、`npx biome`、`node_modules\.bin\*`。

原因：该环境曾出现这些命令异常派生大量 `node.exe`，导致系统卡死。

前端验证优先使用 Docker Compose 已启动的 `http://127.0.0.1:5173` 做浏览器/API 级验证，或请用户手动运行前端命令后回传结果。只有用户明确授权时，才可在说明风险、限定一次命令并设置短超时后运行本机前端 Node 命令。

### 后端

```bash
cd backend

# 安装依赖
uv sync

# 启动开发服务器（需要先启动 Redis）
ENV=DEV uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 120 --reload

# Lint（使用虚拟环境中的 ruff）
.\.venv\Scripts\python.exe -m ruff check app/
.\.venv\Scripts\python.exe -m ruff format app/

# 类型检查
npx pyright app/
```

### 前端

前端本机命令只供用户手动执行参考，agent 默认不得主动运行：

- `pnpm i`
- `pnpm run dev`
- `pnpm run build`
- `vue-tsc`
- `vite build`
- `biome` / `npx biome`

agent 如需验证前端，优先使用 Docker Compose 服务：

```bash
docker compose up --build -d
curl http://127.0.0.1:5173/
```

### Docker

```bash
docker compose up --build -d      # 重建并后台启动
docker compose ps                 # 查看服务状态
docker compose logs backend --tail=200
docker compose down               # 停止
```

Docker 内后端验证：

```bash
docker compose exec backend uv run python -m unittest app.tests.test_scholar_search app.tests.test_security_utils app.tests.test_variable_snapshot_resume app.tests.test_message_history app.tests.test_user_output_and_tasks
docker compose exec backend uv run python -m ruff check app
```

## 项目结构

```
backend/
  app/
    core/
      agents/          # Agent 实现（继承 Agent 基类）
        agent.py       # Agent 基类：对话历史、轮次控制、记忆压缩
        coordinator_agent.py  # 任务分解
        modeler_agent.py      # 数学建模
        coder_agent.py        # 代码生成与执行
        writer_agent.py       # 论文撰写
      llm/             # LLM 调用层（内置 OpenAI Chat/Responses/Anthropic provider）
      prompts/         # 各 Agent 的 prompt 模板
      flows.py         # 编排逻辑（问题拆分、子任务管理）
      workflow.py      # 工作流主入口
    routers/           # FastAPI 路由（REST + WebSocket）
    schemas/           # Pydantic 模型（请求/响应/枚举）
    services/          # Redis 管理、WebSocket 管理
    tools/             # 代码解释器（本地 Jupyter / E2B 云端）、文献搜索、导出工具
    utils/             # 工具函数
    config/            # 配置（Pydantic Settings）

frontend/
  src/
    apis/              # 后端 API 调用封装
    components/        # 通用组件 + shadcn-vue UI 库（components/ui/ 不要修改）
    pages/             # 页面组件（chat/、task/、login/）
    stores/            # Pinia 状态管理
    utils/             # 工具函数、类型定义、WebSocket 客户端
```

## Code Style

### 后端（Python）

- 模块级、类级、公共方法均使用 Google 风格 docstring（Args/Returns/Raises）
- 类型注解：使用 `str | None` 而非 `Optional[str]`
- 异步：全程 async/await，FastAPI 路由均为 async def
- 注释：中文，解释 WHY 而非 WHAT

```python
"""模块级 docstring：描述模块用途。"""

class ExampleAgent:
    """类级 docstring：简述职责。"""

    async def run(self, prompt: str, system_prompt: str) -> str:
        """执行任务并返回结果。

        Args:
            prompt: 用户输入。
            system_prompt: 系统提示词。

        Returns:
            处理结果文本。
        """
```

### 前端（Vue 3 + TypeScript）

- SFC 使用 `<script setup lang="ts">`
- 代码按逻辑分组，用注释分隔：`// ---- Props ----`、`// ---- State ----`、`// ---- Computed ----`、`// ---- Methods ----`
- TypeScript 接口和 API 函数使用 JSDoc `/** */` 注释
- UI 库组件（`components/ui/`）为 shadcn-vue 生成代码，不要修改
- 格式：tab 缩进，双引号，Biome 管理 lint 和格式化

```vue
<script setup lang="ts">
import { ref, computed } from "vue";

// ---- Props ----

/** 组件属性 */
interface Props {
	/** 消息类型 */
	type: "agent" | "user";
	/** 消息内容 */
	content: string;
}
const props = withDefaults(defineProps<Props>(), { type: "user" });

// ---- Computed ----

const rendered = computed(() => marked.parse(props.content));
</script>
```

## Git Workflow

提交信息格式：`<type>: <描述>`，type 包括：

- `feat`: 新功能
- `fix`: 修复
- `refactor`: 重构
- `chore`: 杂项变更
- `enhance`: 增强
- `docs`: 文档

示例：`feat: 添加 OpenAlex API Key 支持并更新相关配置`

## Boundaries

### 自动化 Lint Hook

每次 Edit/Write 文件后，PostToolUse hook 可能自动触发：
- `backend/**/*.py` → `ruff check app/`
- `frontend/src/**/*.{vue,ts}` → `biome check <file>`

hook 脚本位于 `.claude/hook_lint.sh`，配置位于 `.claude/settings.json`。

注意：在当前 Windows 本机环境中，不要依赖或主动触发前端 `biome` hook；前端 Node 工具链存在异常派生大量 `node.exe` 的历史风险。前端改动可以先做代码审查，必要时让用户手动验证或使用 Docker 服务做端到端检查。

### 不要修改的内容

- `frontend/src/components/ui/` — shadcn-vue 第三方 UI 库组件
- 已有的 `# type: ignore` 注释 — 这些是经过验证的类型抑制，非遗留问题
- `.env` 相关文件中的实际配置值

### 运行环境

- Python 3.12+，包管理用 uv（非 pip）
- Node.js，包管理用 pnpm（版本见 packageManager 字段）
- Redis 必须运行（任务队列和 WebSocket 广播）
- 后端虚拟环境路径：`backend/.venv/`

### 文献搜索

- Writer 通过 `search_papers` 工具检索参考文献。
- `backend/app/tools/openalex_scholar.py` 保留 `OpenAlexScholar` 类名，但内部是多源聚合搜索：OpenAlex、Semantic Scholar、Crossref、arXiv，以及可选 Tavily。
- `OPENALEX_EMAIL` 未配置时只跳过 OpenAlex，不禁用其他学术源。
- Tavily 仅在 `TAVILY_API_KEY` 存在且 `SEARCH_ENABLED=true` 时启用，用于网页、官方报告和数据来源补充。
- 不要打印 `TAVILY_API_KEY` / `OPENALEX_API_KEY` 原文。
