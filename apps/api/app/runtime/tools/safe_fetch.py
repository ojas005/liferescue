"""The ONE shared SSRF-safe URL fetcher (checklist S1-S4, S7; invariant I4).

No other module may open a user-influenced URL (tests/runtime/test_runtime_http_boundary.py enforces
which modules may import an HTTP client). Pipeline:

  validate_url()   pure, NO network: scheme/host/port/userinfo/length/IP-literal rules (S1)
  resolve + check  DNS resolved by us, EVERY returned address must be public (S2)
  connect          to the CHECKED ip (pinned) with Host header + SNI/cert name = original host, so
                   DNS rebinding between check and connect is impossible (S2)
  redirects        off by default; if enabled <= 3 hops, each hop fully re-validated, https->http
                   refused, cross-host hops recorded (S3)
  limits           connect 3 s, total 8 s, body <= 1 MB counted AFTER decompression, 4 content types,
                   no cookies / auth headers / proxy env, fixed User-Agent, nothing is executed (S4)
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from ..errors import FetchFailed, SSRFBlocked

Resolver = Callable[[str, int], Awaitable[list[str]]]

BLOCKED_NAMES = frozenset({"localhost", "metadata.google.internal"})
BLOCKED_SUFFIXES = (".local", ".internal", ".localhost")
BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
        "64:ff9b::/96",
    )
]
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml+xml")
USER_AGENT = "LifeRescue-SafeFetch/0.1 (+https://github.com/ojas005/liferescue)"

_BAD_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class FetchPolicy:
    connect_timeout_s: float = 3.0
    total_timeout_s: float = 8.0
    max_bytes: int = 1_000_000
    max_chars: int = 20_000
    max_url_len: int = 2048
    allowed_ports: tuple[int, ...] = (80, 443)
    follow_redirects: bool = False
    max_redirects: int = 3
    allowed_content_types: tuple[str, ...] = ALLOWED_CONTENT_TYPES


@dataclass(frozen=True)
class Target:
    url: str  # normalized, fragment stripped
    scheme: str
    host: str  # lower-case ASCII, no trailing dot
    port: int
    path_query: str


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    truncated: bool
    bytes_read: int
    resolved_ip: str
    redirects: list[dict[str, str]] = field(default_factory=list)
    location: str | None = None  # set when a 3xx was NOT followed


def _parse_v4_loose(host: str) -> ipaddress.IPv4Address | None:
    """inet_aton-style forms: decimal / hex / octal parts, 1-4 parts ('2130706433', '0x7f.1')."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or "" in parts:
        return None
    nums: list[int] = []
    for p in parts:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", p):
            nums.append(int(p, 16))
        elif re.fullmatch(r"0[0-7]*", p):
            nums.append(int(p, 8))
        elif re.fullmatch(r"[1-9][0-9]*", p):
            nums.append(int(p))
        else:
            return None
    *head, last = nums
    if any(h > 255 for h in head) or last >= 256 ** (4 - len(head)):
        return None
    val = last
    for i, h in enumerate(head):
        val += h << (8 * (3 - i))
    return ipaddress.IPv4Address(val)


def ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the address must never be contacted (private, loopback, link-local, metadata,
    mapped/NAT64/6to4 forms of those, or simply not globally routable)."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip_is_blocked(ip.ipv4_mapped)
        if ip.sixtofour is not None and ip_is_blocked(ip.sixtofour):
            return True
        if ip.teredo is not None:
            return True
    if any(ip in n for n in BLOCKED_NETS if n.version == ip.version):
        return True
    return not ip.is_global


def validate_url(url: str, policy: FetchPolicy | None = None) -> Target:
    """Syntactic validation (S1). Performs NO network access. Raises SSRFBlocked."""
    policy = policy or FetchPolicy()
    if not isinstance(url, str) or not url or len(url) > policy.max_url_len:
        raise SSRFBlocked("url empty or too long")
    if _BAD_CHARS.search(url):
        raise SSRFBlocked("url contains whitespace, control or backslash characters")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise SSRFBlocked("url is malformed") from None
    if u.scheme not in ("http", "https") or not u.netloc:
        raise SSRFBlocked("only absolute http(s) urls are allowed")
    if "@" in u.netloc:
        raise SSRFBlocked("userinfo in url is not allowed")
    default_port = 443 if u.scheme == "https" else 80
    port = port or default_port
    if port not in policy.allowed_ports:
        raise SSRFBlocked(f"port {port} is not allowed")
    host = (u.hostname or "").rstrip(".").lower()
    if not host:
        raise SSRFBlocked("url has no host")
    if not host.isascii():
        raise SSRFBlocked("non-ASCII/IDN hosts are refused")
    if host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIXES):
        raise SSRFBlocked("internal host names are refused")
    if ":" in host:
        raise SSRFBlocked("IP literals are refused (domain names only)")
    if _parse_v4_loose(host) is not None:
        raise SSRFBlocked("IP literals in any form are refused (domain names only)")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SSRFBlocked("IP literals are refused (domain names only)")
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise SSRFBlocked("host is not a fully qualified domain name")
    if re.fullmatch(r"[0-9a-f.x]+", host) and re.search(r"\d", labels[-1]):
        raise SSRFBlocked("numeric host forms are refused")
    path_query = (u.path or "/") + (f"?{u.query}" if u.query else "")
    return Target(
        url=f"{u.scheme}://{host}{'' if port == default_port else f':{port}'}{path_query}",
        scheme=u.scheme,
        host=host,
        port=port,
        path_query=path_query,
    )


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchFailed("dns resolution failed") from None
    seen: list[str] = []
    for info in infos:
        ip = str(info[4][0]).split("%")[0]
        if ip not in seen:
            seen.append(ip)
    return seen


async def resolve_checked(target: Target, resolver: Resolver) -> str:
    """Resolve and verify EVERY address (S2). Returns the pinned IP to connect to."""
    ips = await resolver(target.host, target.port)
    if not ips:
        raise FetchFailed("dns returned no addresses")
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw in ips:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            raise SSRFBlocked("resolver returned an invalid address") from None
        if ip_is_blocked(ip):
            raise SSRFBlocked("host resolves to a non-public address")
        parsed.append(ip)
    return str(parsed[0])


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return "\n".join(p.parts)


def _ip_url(target: Target, ip: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    default = 443 if target.scheme == "https" else 80
    return f"{target.scheme}://{host}{'' if target.port == default else f':{target.port}'}{target.path_query}"


async def safe_fetch(
    url: str,
    *,
    policy: FetchPolicy | None = None,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchedPage:
    """Fetch `url` safely. Raises SSRFBlocked (validation/DNS/redirect) or FetchFailed."""
    policy = policy or FetchPolicy()
    resolver = resolver or default_resolver
    try:
        async with asyncio.timeout(policy.total_timeout_s):
            return await _fetch(url, policy, resolver, transport)
    except TimeoutError:
        raise FetchFailed("fetch timed out") from None


async def _fetch(
    url: str, policy: FetchPolicy, resolver: Resolver, transport: httpx.AsyncBaseTransport | None
) -> FetchedPage:
    redirects: list[dict[str, str]] = []
    current = url
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,  # no proxy env vars, no netrc
        follow_redirects=False,
        cookies=None,
        timeout=httpx.Timeout(policy.total_timeout_s, connect=policy.connect_timeout_s),
    ) as client:
        for hop in range(policy.max_redirects + 1):
            target = validate_url(current, policy)
            ip = await resolve_checked(target, resolver)
            request = client.build_request(
                "GET",
                _ip_url(target, ip),
                headers={
                    "Host": target.host,
                    "User-Agent": USER_AGENT,
                    "Accept": ", ".join(policy.allowed_content_types),
                    "Accept-Encoding": "identity",
                },
                extensions={"sni_hostname": target.host},
            )
            try:
                resp = await client.send(request, stream=True)
            except httpx.TimeoutException:
                raise FetchFailed("fetch timed out") from None
            except httpx.HTTPError as exc:
                raise FetchFailed(f"fetch transport error: {type(exc).__name__}") from None
            try:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not policy.follow_redirects or not loc:
                        return FetchedPage(
                            url=url,
                            final_url=target.url,
                            status=resp.status_code,
                            content_type="",
                            text="",
                            truncated=False,
                            bytes_read=0,
                            resolved_ip=ip,
                            redirects=redirects,
                            location=(loc or "")[:500] or None,
                        )
                    if hop >= policy.max_redirects:
                        raise SSRFBlocked("too many redirects")
                    nxt = urljoin(target.url, loc)
                    nxt_scheme = urlsplit(nxt).scheme
                    if target.scheme == "https" and nxt_scheme != "https":
                        raise SSRFBlocked("https -> http downgrade redirect refused")
                    redirects.append(
                        {"from": target.url[:200], "to": nxt[:200], "status": str(resp.status_code)}
                    )
                    current = nxt  # re-validated (S1+S2) at the top of the loop
                    continue
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in policy.allowed_content_types:
                    raise FetchFailed(f"content type {ctype or 'unknown'!r} is not allowed")
                body = bytearray()
                truncated = False
                async for (
                    chunk
                ) in resp.aiter_bytes():  # decoded stream => cap is post-decompression
                    room = policy.max_bytes - len(body)
                    body += chunk[:room]
                    if len(chunk) > room:
                        truncated = True
                        break
                charset = "utf-8"
                m = re.search(r"charset=([\w-]+)", resp.headers.get("content-type", ""), re.I)
                if m:
                    charset = m.group(1)
                try:
                    text = bytes(body).decode(charset, errors="replace")
                except LookupError:
                    text = bytes(body).decode("utf-8", errors="replace")
                if ctype in ("text/html", "application/xhtml+xml"):
                    text = html_to_text(text)
                if len(text) > policy.max_chars:
                    text, truncated = text[: policy.max_chars], True
                return FetchedPage(
                    url=url,
                    final_url=target.url,
                    status=resp.status_code,
                    content_type=ctype,
                    text=text,
                    truncated=truncated,
                    bytes_read=len(body),
                    resolved_ip=ip,
                    redirects=redirects,
                )
            finally:
                await resp.aclose()
    raise SSRFBlocked("too many redirects")  # pragma: no cover
