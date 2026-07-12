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

    MAX_CHAT_TURNS: Optional[int] = None
    MAX_RETRIES: Optional[int] = None
    CODER_MAX_SUCCESSFUL_TOOL_CALLS_PER_SUBTASK: Optional[int] = 8
    LLM_REQUEST_TIMEOUT_SECONDS: float = 90.0
    HUMAN_MODEL_GATE_ENABLED: bool = False
    E2B_API_KEY: Optional[str] = None
    # 代码手会执行模型生成的代码。默认只允许远程隔离环境，避免在后端进程中
    # 直接执行不可信代码并读取服务端环境变量或项目文件。
    CODE_INTERPRETER_KIND: Literal["remote", "local"] = "remote"
    ALLOW_LOCAL_CODE_EXECUTION: bool = False
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
