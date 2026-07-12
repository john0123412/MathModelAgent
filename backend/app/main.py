"""MathModelAgent 应用入口，配置 FastAPI 应用和中间件。"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
import os
from app.routers import modeling_router, ws_router, common_router, files_router
from app.utils.log_util import logger
from fastapi.responses import JSONResponse
from app.utils.cli import get_ascii_banner, center_cli_str
from app.config.setting import settings

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
