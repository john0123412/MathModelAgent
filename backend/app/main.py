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

class RequestBodyLimitMiddleware:
    """Limit streamed HTTP request bodies without replacing ``Request._receive``.

    Starlette's ``BaseHTTPMiddleware`` exposes a ``Request`` object whose private
    receive callback is easy to wrap incorrectly: a closure that reads
    ``request._receive`` after assigning itself recursively calls itself and can
    also lose messages when a body arrives in several chunks.  This middleware
    stays at the ASGI boundary and wraps the original ``receive`` callable once,
    preserving every message and counting each ``http.request`` body chunk.
    """

    def __init__(self, app, max_body_bytes: int | None = None):
        self.app = app
        self.max_body_bytes = max_body_bytes

    @staticmethod
    async def _send_too_large(send) -> None:
        body = b'{"detail":"\\u8bf7\\u6c42\\u4f53\\u8d85\\u8fc7\\u5141\\u8bb8\\u4e0a\\u9650"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self.max_body_bytes
        if limit is None:
            limit = settings.MAX_REQUEST_BODY_BYTES

        headers = dict(scope.get("headers") or ())
        content_length = headers.get(b"content-length")
        declared_length: int | None = None
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                pass
            if declared_length is not None and declared_length >= 0:
                if declared_length > limit:
                    await self._send_too_large(send)
                    return

        # Count all request chunks even when Content-Length is present.  A
        # small declaration is not permission to skip accounting: a malformed
        # request can carry both Content-Length and Transfer-Encoding, or send
        # more bytes than it declared.  The latter is rejected at the first
        # excess byte, while a truthful declaration still benefits from the
        # quick-reject path above when it already exceeds the configured limit.
        stream_limit = limit
        if declared_length is not None and declared_length >= 0:
            stream_limit = min(limit, declared_length)
        received = 0
        rejected = False

        async def guarded_send(message):
            # Once the limiter has emitted 413, suppress an inner
            # BaseHTTPMiddleware/FastAPI error response (usually 400 from a
            # deliberate http.disconnect) so the client sees the real cause.
            if not rejected:
                await send(message)

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > stream_limit:
                    rejected = True
                    await self._send_too_large(send)
                    return {"type": "http.disconnect"}
            return message

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:
                raise

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
    print(center_cli_str("GitHub:https://github.com/john0123412/MathModelAgent"))
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

# Keep request-body accounting at the ASGI boundary.  This is intentionally
# added after the regular middleware declarations so it is the outermost layer
# and can reject an oversized stream before FastAPI starts parsing it.
app.add_middleware(RequestBodyLimitMiddleware)
