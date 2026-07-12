"""Security boundaries for externally supplied runtime configuration."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}


def validate_llm_base_url(
    base_url: str | None,
    *,
    allow_private_hosts: bool = False,
    resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
) -> str | None:
    """Validate an LLM endpoint before the backend makes an outbound request.

    Compatible-provider endpoints are supported, but local, private, and non-HTTPS
    endpoints require an explicit opt-in so a browser request cannot turn the backend
    into an SSRF proxy by default.
    """
    if base_url is None:
        return None

    normalized = str(base_url).strip().rstrip("/")
    if not normalized:
        return None

    parsed = urlparse(normalized)
    allowed_schemes = {"https"}
    if allow_private_hosts:
        allowed_schemes.add("http")
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise ValueError("LLM Base URL 必须使用受允许的绝对 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.params:
        raise ValueError("LLM Base URL 不能包含凭据、查询参数或片段")

    hostname = parsed.hostname.rstrip(".").lower()
    if not allow_private_hosts:
        if _is_private_host(hostname):
            raise ValueError("LLM Base URL 不能指向本地或内网主机")
        _require_public_dns_resolution(hostname, parsed.port or 443, resolver)
    return normalized


def _is_private_host(hostname: str) -> bool:
    if hostname in _PRIVATE_HOSTNAMES or hostname.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        return not ipaddress.ip_address(hostname).is_global
    except ValueError:
        return False


def _require_public_dns_resolution(
    hostname: str,
    port: int,
    resolver: Callable[..., list[tuple]],
) -> None:
    """Reject hostnames that resolve to a non-public address.

    This prevents a public-looking hostname from being used as a simple SSRF
    bypass. Redirect following is separately disabled in the LLM HTTP clients.
    """
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if not literal_ip.is_global:
            raise ValueError("LLM Base URL 不能指向本地或内网主机")
        return

    try:
        addresses = resolver(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("LLM Base URL 主机无法解析") from exc

    if not addresses:
        raise ValueError("LLM Base URL 主机无法解析")

    for address in addresses:
        resolved_host = address[4][0]
        try:
            resolved_ip = ipaddress.ip_address(resolved_host)
        except ValueError as exc:
            raise ValueError("LLM Base URL 主机解析结果不合法") from exc
        if not resolved_ip.is_global:
            raise ValueError("LLM Base URL 不能解析到本地或内网地址")
