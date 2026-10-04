"""Tool layer: registry, the single ToolGateway execution path, Tavily (READ), SSRF-safe fetch.
Network client libraries are allowed here (contract rule R2) and nowhere else in the runtime."""

from .gateway import (
    FetchUrlParams,
    RuntimeToolGateway,
    WebSearchParams,
    register_fetch_url,
    register_mock_write,
    register_web_search,
    strict_schema,
    validate_params,
)
from .safe_fetch import FetchedPage, FetchPolicy, safe_fetch, validate_url
from .tavily import TavilyProvider

__all__ = [
    "FetchPolicy",
    "FetchUrlParams",
    "FetchedPage",
    "RuntimeToolGateway",
    "TavilyProvider",
    "WebSearchParams",
    "register_fetch_url",
    "register_mock_write",
    "register_web_search",
    "safe_fetch",
    "strict_schema",
    "validate_params",
    "validate_url",
]
