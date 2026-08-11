"""MathModelAgent 应用入口，配置 FastAPI 应用和中间件。"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import os
import sys
from app.routers import modeling_router, ws_router, common_router, files_router
from app.utils.log_util import logger
from fastapi.responses import JSONResponse
from app.utils.cli import get_ascii_banner, center_cli_str
from app.utils.security import is_valid_bearer_authorization
from app.config.setting import settings
from app.services.task_status import recover_stale_task_statuses

cors_allow_origins = (
    settings.CORS_ALLOW_ORIGINS
    if isinstance(settings.CORS_ALLOW_ORIGINS, list)
    else [settings.CORS_ALLOW_ORIGINS]
)
trusted_hosts = (
    settings.TRUSTED_HOSTS
    if isinstance(settings.TRUSTED_HOSTS, list)
    else [settings.TRUSTED_HOSTS]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(get_ascii_banner())
    print(center_cli_str("GitHub:https://github.com/jihe520/MathModelAgent"))
    logger.info("Starting MathModelAgent")

    PROJECT_FOLDER = "./project"
    os.makedirs(PROJECT_FOLDER, exist_ok=True)
    # ``python -m unittest discover app/tests`` imports test modules by their
    # bare names, so ``app.tests.__init__`` is not guaranteed to run first.
    # Never let a host-side TestClient mutate the Docker service's shared
    # work_dir merely because the process inherited the production default.
    is_unittest_process = "unittest" in sys.modules
    recovery_enabled = settings.RECOVER_STALE_TASKS_ON_STARTUP and not is_unittest_process
    if recovery_enabled:
        recovered_tasks = recover_stale_task_statuses()
        if recovered_tasks:
            logger.warning("已将 {} 个遗留活动任务标记为 interrupted: {}", len(recovered_tasks), ", ".join(recovered_tasks[:20]))
    else:
        reason = "unittest 测试进程" if is_unittest_process else "配置开关"
        logger.info("当前进程因 {} 禁用遗留任务恢复，不改写共享工作目录状态", reason)

    yield
    logger.info("Stopping MathModelAgent")


app = FastAPI(
    title="MathModelAgent",
    description="Agents for MathModel",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(modeling_router.router)
app.include_router(ws_router.router)
app.include_router(common_router.router)
app.include_router(files_router.router)


# 令牌鉴权豁免路径：仅接口文档保持公开，便于部署方查阅接口说明。
_AUTH_EXEMPT_PATHS = {"/docs", "/redoc", "/openapi.json"}


@app.middleware("http")
async def require_api_auth_token(request, call_next):
    """可选令牌鉴权：配置 API_AUTH_TOKEN 后所有非豁免接口要求 Bearer 令牌。

    默认（API_AUTH_TOKEN=None）不启用，保持纯本机部署的零配置行为。
    前端尚未适配令牌模式，该开关面向需要在受信网络之外暴露服务的部署方
    opt-in 使用；/static 产物路径依赖 <img> 直连且 task_id 本身是 128 位
    随机 capability URL，同样豁免以免令牌模式下图表预览完全不可用。
    """
    token = settings.API_AUTH_TOKEN
    if token:
        path = request.url.path
        if path not in _AUTH_EXEMPT_PATHS and not path.startswith("/static/"):
            if not is_valid_bearer_authorization(
                request.headers.get("authorization"), token
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "缺少或无效的 API 访问令牌"},
                )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Apply conservative headers to API, docs, and generated static files."""
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdecimal():
        if int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "请求体超过允许上限"},
            )

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
    return response


# 跨域 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
