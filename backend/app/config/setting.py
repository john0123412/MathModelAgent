"""应用配置模块，基于 pydantic-settings 管理环境变量和全局配置。"""

from enum import Enum

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Annotated, Literal, Optional


DEFAULT_CORS_ALLOW_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
DEFAULT_TRUSTED_HOSTS = ["localhost", "127.0.0.1", "backend"]


class ApiType(str, Enum):
    """LLM API 类型。"""
    OPENAI_CHAT = "openai-chat"
    OPENAI_RESPONSES = "openai-responses"
    ANTHROPIC = "anthropic"


def parse_cors(value: str | list[str]) -> list[str]:
    """将 CORS 配置字符串解析为 URL 列表。

    Args:
        value: 逗号分隔的 URL 字符串或 URL 列表。

    Returns:
        解析后的 URL 列表。
    """
    if isinstance(value, list):
        origins = [str(url).strip() for url in value]
    else:
        origins = [url.strip() for url in value.split(",")]

    origins = [url for url in origins if url]
    if not origins or "*" in origins:
        raise ValueError("CORS_ALLOW_ORIGINS 必须是明确的受信任 Origin，不能使用通配符")
    return origins


def parse_trusted_hosts(value: str | list[str]) -> list[str]:
    """Parse explicit Host header allowlist without accepting a wildcard."""
    if isinstance(value, list):
        hosts = [str(host).strip() for host in value]
    else:
        hosts = [host.strip() for host in value.split(",")]

    hosts = [host for host in hosts if host]
    if not hosts or "*" in hosts:
        raise ValueError("TRUSTED_HOSTS 必须是明确的 Host 列表，不能使用通配符")
    return hosts


class Settings(BaseSettings):
    """全局应用配置，从环境变量和 .env 文件加载。"""
    ENV: str = "dev"

    COORDINATOR_API_TYPE: Optional[ApiType] = None
    COORDINATOR_API_KEY: Optional[str] = None
    COORDINATOR_MODEL: Optional[str] = None
    COORDINATOR_BASE_URL: Optional[str] = None
    COORDINATOR_MAX_TOKENS: Optional[int] = None
    COORDINATOR_CONTEXT_WINDOW: int = 128000

    MODELER_API_TYPE: Optional[ApiType] = None
    MODELER_API_KEY: Optional[str] = None
    MODELER_MODEL: Optional[str] = None
    MODELER_BASE_URL: Optional[str] = None
    MODELER_MAX_TOKENS: Optional[int] = None
    MODELER_CONTEXT_WINDOW: int = 128000

    CODER_API_TYPE: Optional[ApiType] = None
    CODER_API_KEY: Optional[str] = None
    CODER_MODEL: Optional[str] = None
    CODER_BASE_URL: Optional[str] = None
    CODER_MAX_TOKENS: Optional[int] = None
    CODER_CONTEXT_WINDOW: int = 128000

    WRITER_API_TYPE: Optional[ApiType] = None
    WRITER_API_KEY: Optional[str] = None
    WRITER_MODEL: Optional[str] = None
    WRITER_BASE_URL: Optional[str] = None
    WRITER_MAX_TOKENS: Optional[int] = None
    WRITER_CONTEXT_WINDOW: int = 128000

    # 熔断边界：以下两个值是防失控保险丝，不是紧预算。曾经默认 None（无限制），
    # 当 LLM 持续故障（欠费/断网）时 CoderAgent 外层循环会紧循环打 API 直到
    # 任务超时，因此默认值必须有限。
    # MAX_CHAT_TURNS：CoderAgent 实例级累计、跨子任务不重置；一个任务约 6-9
    # 个子任务、每个正常消耗十几轮，200 轮留足余量，只拦截失控场景。
    MAX_CHAT_TURNS: Optional[int] = 200
    # MAX_RETRIES：单个子任务内的重试计数（run() 局部变量、每子任务重置），
    # 覆盖代码报错反思与 LLM 故障兜底重试；内层 llm.py 每次调用已自带 3 次
    # 重试，外层 20 次足够跨越常见抖动，同时避免持续故障时无限烧钱。
    MAX_RETRIES: Optional[int] = 20
    # LLM_MAX_RETRIES：llm.py 单次 chat 调用内的重试次数。远程网关（如中转
    # 服务）偶发连接抖动时，默认 3 次约 6 秒的窗口经常跨不过一次抖动；按
    # provider 稳定性在 env 中调大。
    LLM_MAX_RETRIES: int = 3
    CODER_MAX_SUCCESSFUL_TOOL_CALLS_PER_SUBTASK: Optional[int] = 8
    LLM_REQUEST_TIMEOUT_SECONDS: float = 90.0
    # reasoning_effort 透传（minimal/low/medium/high）；None=不传，走模型默认。
    # 仅 openai-chat 形态且 thinking=True 时生效；thinking=False 的强制禁思考
    # 调用（如 Modeler JSON 修复、Coder 首轮）优先级更高，不会携带该参数。
    LLM_REASONING_EFFORT: Optional[str] = None
    # Operator-controlled explicit egress proxy for LLM API calls.  Unlike
    # HTTP_PROXY/HTTPS_PROXY, this does not let arbitrary process environment
    # variables alter outbound routing; the destination URL still passes the
    # normal public-host/SSRF validation before every call.
    LLM_OUTBOUND_PROXY: Optional[str] = None
    HUMAN_MODEL_GATE_ENABLED: bool = False
    # A real backend process should recover active tasks left by a prior
    # process.  TestClient/lint subprocesses share the host work_dir during
    # development, so their test package explicitly disables this side effect.
    RECOVER_STALE_TASKS_ON_STARTUP: bool = True
    E2B_API_KEY: Optional[str] = None
    # 代码手会执行模型生成的代码。默认只允许远程隔离环境，避免在后端进程中
    # 直接执行不可信代码并读取服务端环境变量或项目文件。auto 仅在显式允许
    # 本地执行时才会在 E2B 不可用后降级。
    CODE_INTERPRETER_KIND: Literal["remote", "local", "auto"] = "remote"
    ALLOW_LOCAL_CODE_EXECUTION: bool = False
    LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS: int = 300
    LOG_LEVEL: str = "DEBUG"
    DEBUG: bool = True
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_MAX_CONNECTIONS: int = 10
    CORS_ALLOW_ORIGINS: Annotated[list[str] | str, BeforeValidator(parse_cors)] = (
        DEFAULT_CORS_ALLOW_ORIGINS
    )
    TRUSTED_HOSTS: Annotated[list[str] | str, BeforeValidator(parse_trusted_hosts)] = (
        DEFAULT_TRUSTED_HOSTS
    )
    ALLOW_PRIVATE_LLM_BASE_URLS: bool = False
    # 可选令牌鉴权：配置后所有非公开 HTTP 接口与 WebSocket 都要求携带该令牌
    # （HTTP 用 Authorization: Bearer <token>，WebSocket 用查询参数 token）。
    # 默认 None 保持原有无鉴权行为，适用于纯本机部署。
    API_AUTH_TOKEN: Optional[str] = None
    MAX_UPLOAD_FILE_SIZE_BYTES: int = 50 * 1024 * 1024
    MAX_UPLOAD_TOTAL_SIZE_BYTES: int = 200 * 1024 * 1024
    MAX_PROBLEM_TEXT_CHARS: int = 100_000
    MAX_REQUEST_BODY_BYTES: int = 210 * 1024 * 1024
    SERVER_HOST: str = "http://localhost:8003"
    DEEPSEEK_MODEL: Optional[str] = None
    DEEPSEEK_BASE_URL: Optional[str] = None
    OPENALEX_EMAIL: Optional[str] = None
    OPENALEX_API_KEY: Optional[str] = None

    # Web Search 配置（Tavily API）
    TAVILY_API_KEY: Optional[str] = None
    SEARCH_CACHE_TTL: int = 86400  # 搜索缓存过期时间（秒）
    SEARCH_ENABLED: bool = False

    # RAG 知识库配置
    RAG_ENABLED: bool = False
    RAG_DB_PATH: str = "data/chromadb"
    RAG_TOP_K: int = 5
    RAG_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    RAG_RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # HIL 人机协作配置
    HIL_ENABLED: bool = True
    HIL_TIMEOUT: int = 300  # 审批超时时间（秒）
    HIL_CHECKPOINTS: dict = {
        "problem_split": True,
        "model_selection": True,
        "code_review": False,
        "paper_review": True,
    }

    # 预留功能开关：当前仅用于 /status guardrail warning，不代表已接入主工作流
    FALLBACK_ENABLED: bool = False
    EVALUATOR_ENABLED: bool = False

    model_config = SettingsConfigDict(
        env_file=".env.dev",
        env_file_encoding="utf-8",
        extra="allow",
    )

    @classmethod
    def from_env(cls, env: str | None = None):
        """根据环境名称加载对应配置。

        Args:
            env: 环境名称（如 dev、prod），默认从 ENV 环境变量获取。
        """
        env = env or os.getenv("ENV", "dev")
        env_file = f".env.{env.lower()}"
        return cls(_env_file=env_file, _env_file_encoding="utf-8")  # type: ignore[call-arg]


settings = Settings()
