"""Hardened HTTP client construction for third-party LLM providers."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from app.config.setting import settings


@asynccontextmanager
async def llm_http_client(timeout: float) -> AsyncIterator[httpx.AsyncClient]:
    """Create a client that cannot follow an unvalidated redirect.

    The configured base URL is validated before construction. Redirects and proxy
    environment variables could otherwise bypass that validation at request time.
    """
    client_options: dict = {
        "timeout": timeout,
        "follow_redirects": False,
        "trust_env": False,
    }
    # Some Docker Desktop installations cannot directly complete TLS with a
    # provider even though the Windows host can.  Accept only this explicit,
    # deployment-owned setting; do not inherit ambient proxy variables, which
    # could bypass the deployment's routing policy unexpectedly.
    if settings.LLM_OUTBOUND_PROXY:
        client_options["proxy"] = settings.LLM_OUTBOUND_PROXY

    async with httpx.AsyncClient(**client_options) as client:
        yield client
