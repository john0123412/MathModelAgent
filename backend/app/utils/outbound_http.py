"""Hardened HTTP client construction for third-party LLM providers."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx


@asynccontextmanager
async def llm_http_client(timeout: float) -> AsyncIterator[httpx.AsyncClient]:
    """Create a client that cannot follow an unvalidated redirect.

    The configured base URL is validated before construction. Redirects and proxy
    environment variables could otherwise bypass that validation at request time.
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        yield client
