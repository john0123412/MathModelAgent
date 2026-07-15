"""Security boundaries for externally supplied runtime configuration."""

from __future__ import annotations

import ipaddress
import secrets
import socket
import time
from collections.abc import Callable
from urllib.parse import urlparse

_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}
_DNS_RESOLUTION_ATTEMPTS = 3
_DNS_RETRY_DELAY_SECONDS = 0.1
_BEARER_PREFIX = "Bearer "


def _compare_tokens(candidate: str, expected_token: str) -> bool:
    """恒定时间比较两个令牌字符串。

    compare_digest 对混合非 ASCII 的 str 会抛 TypeError，统一按 UTF-8
    编码为 bytes 后比较，保证任意外部输入都不会触发异常。
    """
    return secrets.compare_digest(
        candidate.encode("utf-8"), expected_token.encode("utf-8")
    )


def is_valid_bearer_authorization(
    authorization: str | None, expected_token: str
) -> bool:
    """校验 HTTP Authorization 头是否为精确匹配的 Bearer 令牌。

    Args:
        authorization: 请求携带的 Authorization 头原文，可能缺失。
        expected_token: 部署方配置的 API_AUTH_TOKEN。

    Returns:
        头部为 "Bearer <expected_token>" 精确匹配时返回 True。
    """
    if not authorization or not expected_token:
        return False
    # 前缀要求精确的 "Bearer "（区分大小写），避免宽松解析引入歧义
    if not authorization.startswith(_BEARER_PREFIX):
        return False
    return _compare_tokens(authorization[len(_BEARER_PREFIX) :], expected_token)


def is_valid_websocket_token(token: str | None, expected_token: str) -> bool:
    """校验 WebSocket 查询参数 token 是否与配置令牌精确匹配。

    Args:
        token: 连接 URL 中的 token 查询参数，可能缺失。
        expected_token: 部署方配置的 API_AUTH_TOKEN。

    Returns:
        完全一致时返回 True。
    """
    if not token or not expected_token:
        return False
    return _compare_tokens(token, expected_token)


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

    addresses: list[tuple] | None = None
    last_error: OSError | None = None
    for attempt in range(_DNS_RESOLUTION_ATTEMPTS):
        try:
            addresses = resolver(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            last_error = exc
            if attempt + 1 < _DNS_RESOLUTION_ATTEMPTS:
                time.sleep(_DNS_RETRY_DELAY_SECONDS * (attempt + 1))
            continue
        break

    if addresses is None:
        raise ValueError("LLM Base URL 主机无法解析") from last_error

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
