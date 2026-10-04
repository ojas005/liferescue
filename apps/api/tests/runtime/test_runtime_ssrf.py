"""SSRF-safe fetch (S1-S4, S7) against the shared corpus + behavioural tests with fake DNS/HTTP."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import httpx
import pytest
from demo_support import run_async

from app.runtime.errors import FetchFailed, SSRFBlocked
from app.runtime.tools import FetchPolicy, safe_fetch, validate_url
from app.runtime.tools.safe_fetch import ip_is_blocked

CORPUS = json.loads((Path(__file__).parent / "corpus" / "ssrf-urls.json").read_text())["cases"]
PUBLIC = "93.184.216.34"


def never_network(req: httpx.Request) -> httpx.Response:
    raise AssertionError(f"network call attempted: {req.url}")


async def no_dns(host: str, port: int) -> list[str]:
    raise AssertionError("DNS attempted for a URL that must be refused at validation")


def resolver_for(mapping: dict[str, list[str]]):
    async def r(host: str, port: int) -> list[str]:
        return mapping[host]

    return r


def fetch(url, mapping=None, handler=None, **policy):
    return run_async(
        safe_fetch(
            url,
            policy=FetchPolicy(**policy),
            resolver=resolver_for(mapping or {}),
            transport=httpx.MockTransport(handler or never_network),
        )
    )


@pytest.mark.parametrize(
    "case", [c for c in CORPUS if c["expect"] == "block"], ids=lambda c: c["id"]
)
def test_corpus_block_cases_refused_at_validation_without_any_network(case):
    with pytest.raises(SSRFBlocked):
        validate_url(case["url"])
    with pytest.raises(SSRFBlocked):  # full fetch path: no DNS, no HTTP
        run_async(
            safe_fetch(case["url"], resolver=no_dns, transport=httpx.MockTransport(never_network))
        )


@pytest.mark.parametrize(
    "case", [c for c in CORPUS if c["expect"] == "allow"], ids=lambda c: c["id"]
)
def test_corpus_allow_cases_pass_validation(case):
    t = validate_url(case["url"])
    assert t.host.endswith((".com", ".org"))


@pytest.mark.parametrize(
    "case", [c for c in CORPUS if c["expect"] == "block_if_resolves_private"], ids=lambda c: c["id"]
)
def test_corpus_names_resolving_private_are_blocked_after_dns(case):
    host = validate_url(case["url"]).host
    for ip in ("127.0.0.1", "169.254.169.254", "10.1.2.3", "::1", "::ffff:127.0.0.1"):
        with pytest.raises(SSRFBlocked):
            fetch(case["url"], {host: [ip]})


def test_corpus_is_complete():
    assert len(CORPUS) == 67


def test_any_private_address_among_many_blocks_the_fetch():
    with pytest.raises(SSRFBlocked):
        fetch("https://rebind.example.com/", {"rebind.example.com": [PUBLIC, "10.0.0.7"]})


def test_ip_classification_table():
    for bad in (
        "0.0.0.0",
        "10.1.1.1",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "172.16.5.5",
        "192.0.0.1",
        "192.168.1.1",
        "198.18.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "::",
        "::1",
        "fd00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::1",
        "192.0.2.1",
    ):
        assert ip_is_blocked(ipaddress.ip_address(bad)), bad
    for good in (PUBLIC, "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"):
        assert not ip_is_blocked(ipaddress.ip_address(good)), good


def test_connects_to_pinned_checked_ip_with_host_header_and_sni():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(req.url),
            host=req.headers["host"],
            ua=req.headers["user-agent"],
            sni=req.extensions.get("sni_hostname"),
            headers=dict(req.headers),
        )
        return httpx.Response(
            200, headers={"content-type": "text/plain; charset=utf-8"}, text="hello"
        )

    page = fetch("https://news.example.org/story?a=1", {"news.example.org": [PUBLIC]}, handler)
    assert page.text == "hello" and page.resolved_ip == PUBLIC and page.status == 200
    assert seen["url"] == f"https://{PUBLIC}/story?a=1"  # connect target = checked IP
    assert seen["host"] == "news.example.org" and seen["sni"] == "news.example.org"
    assert seen["ua"].startswith("LifeRescue-SafeFetch")
    for h in ("authorization", "cookie", "proxy-authorization"):
        assert h not in seen["headers"]


def test_redirects_not_followed_by_default():
    def handler(req):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    page = fetch("https://example.com/r", {"example.com": [PUBLIC]}, handler)
    assert page.status == 302 and page.location == "http://127.0.0.1/admin" and page.text == ""


def test_followed_redirect_is_revalidated_each_hop():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    with pytest.raises(SSRFBlocked):
        fetch("https://example.com/r", {"example.com": [PUBLIC]}, handler, follow_redirects=True)
    assert len(calls) == 1  # the private hop was never requested

    def to_private_name(req):
        return httpx.Response(301, headers={"location": "https://sneaky.example.net/"})

    with pytest.raises(SSRFBlocked):  # public-looking name that resolves to metadata
        fetch(
            "https://example.com/r",
            {"example.com": [PUBLIC], "sneaky.example.net": ["169.254.169.254"]},
            to_private_name,
            follow_redirects=True,
        )


def test_redirect_downgrade_loop_and_cross_host_logging():
    def downgrade(req):
        return httpx.Response(301, headers={"location": "http://example.com/plain"})

    with pytest.raises(SSRFBlocked, match="downgrade"):
        fetch("https://example.com/", {"example.com": [PUBLIC]}, downgrade, follow_redirects=True)

    def loop(req):
        return httpx.Response(302, headers={"location": "https://example.com/again"})

    with pytest.raises(SSRFBlocked, match="too many"):
        fetch("https://example.com/", {"example.com": [PUBLIC]}, loop, follow_redirects=True)

    def hop(req):
        if req.headers["host"] == "example.com":
            return httpx.Response(302, headers={"location": "https://other.example.org/x"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="done")

    page = fetch(
        "https://example.com/",
        {"example.com": [PUBLIC], "other.example.org": ["8.8.8.8"]},
        hop,
        follow_redirects=True,
    )
    assert page.text == "done" and page.redirects[0]["to"] == "https://other.example.org/x"


def test_content_type_allowlist_and_size_cap_and_html_text_extraction():
    with pytest.raises(FetchFailed, match="content type"):
        fetch(
            "https://example.com/",
            {"example.com": [PUBLIC]},
            lambda r: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF"
            ),
        )
    with pytest.raises(FetchFailed, match="content type"):
        fetch(
            "https://example.com/",
            {"example.com": [PUBLIC]},
            lambda r: httpx.Response(200, content=b"x"),
        )
    big = httpx.Response(200, headers={"content-type": "text/plain"}, content=b"a" * 5000)
    page = fetch("https://example.com/", {"example.com": [PUBLIC]}, lambda r: big, max_bytes=1000)
    assert page.truncated and page.bytes_read == 1000 and len(page.text) == 1000
    html = "<html><script>alert(1)</script><style>p{}</style><p>Hi <b>there</b></p></html>"
    page = fetch(
        "https://example.com/",
        {"example.com": [PUBLIC]},
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=html),
    )
    assert "alert" not in page.text and "Hi" in page.text and "there" in page.text
    capped = fetch(
        "https://example.com/",
        {"example.com": [PUBLIC]},
        lambda r: httpx.Response(200, headers={"content-type": "text/plain"}, text="b" * 500),
        max_chars=100,
    )
    assert capped.truncated and len(capped.text) == 100


def test_decompressed_size_is_capped():
    import gzip

    payload = gzip.compress(b"z" * 200_000)  # tiny on the wire, big after decompression

    def handler(req):
        return httpx.Response(
            200, headers={"content-type": "text/plain", "content-encoding": "gzip"}, content=payload
        )

    page = fetch("https://example.com/", {"example.com": [PUBLIC]}, handler, max_bytes=10_000)
    assert page.bytes_read == 10_000 and page.truncated


def test_timeouts_and_transport_errors_are_typed():
    def slow(req):
        raise httpx.ConnectTimeout("t", request=req)

    with pytest.raises(FetchFailed, match="timed out"):
        fetch("https://example.com/", {"example.com": [PUBLIC]}, slow)

    def broken(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(FetchFailed):
        fetch("https://example.com/", {"example.com": [PUBLIC]}, broken)

    async def hang(host, port):
        import asyncio

        await asyncio.sleep(5)
        return [PUBLIC]

    with pytest.raises(FetchFailed, match="timed out"):  # total deadline covers DNS too
        run_async(
            safe_fetch(
                "https://example.com/",
                policy=FetchPolicy(total_timeout_s=0.05),
                resolver=hang,
                transport=httpx.MockTransport(never_network),
            )
        )


def test_dns_failure_and_empty_answer():
    with pytest.raises(FetchFailed):
        fetch("https://example.com/", {"example.com": []})


def test_policy_defaults_match_security_requirements():
    p = FetchPolicy()
    assert (p.connect_timeout_s, p.total_timeout_s, p.max_bytes, p.max_redirects) == (
        3.0,
        8.0,
        1_000_000,
        3,
    )
    assert p.follow_redirects is False and p.allowed_ports == (80, 443) and p.max_url_len == 2048
    assert set(p.allowed_content_types) == {
        "text/html",
        "text/plain",
        "application/json",
        "application/xhtml+xml",
    }
