#!/usr/bin/env python3
"""Checks that ssrf-urls.json agrees with an independent, simple URL classifier (stdlib only, no network).
This is NOT the product's guard; it only proves the corpus labels are right. Exit 1 on any disagreement."""
import ipaddress, json, os, re, sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_NAMES = {"localhost", "metadata.google.internal"}
BLOCK_SUFFIX = (".local", ".internal", ".localhost")
NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4", "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "64:ff9b::/96")]

def parse_v4_loose(host):
    """inet_aton-style: decimal/hex/octal parts, 1-4 parts."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or "" in parts: return None
    nums = []
    for p in parts:
        try:
            if re.fullmatch(r"0[xX][0-9a-fA-F]+", p): nums.append(int(p, 16))
            elif re.fullmatch(r"0[0-7]*", p): nums.append(int(p, 8))
            elif re.fullmatch(r"[1-9][0-9]*", p): nums.append(int(p))
            else: return None
        except ValueError: return None
    *head, last = nums
    if any(h > 255 for h in head) or last >= 256 ** (4 - len(head)): return None
    val = last
    for i, h in enumerate(head): val += h << (8 * (3 - i))
    return ipaddress.IPv4Address(val)

def bad_ip(ip):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped: ip = ip.ipv4_mapped
    return any(ip in n for n in NETS if n.version == ip.version)

def classify(url):
    """Return 'block' or 'allow' (syntactic stage only)."""
    if len(url) > 2048 or re.search(r"[\x00-\x20\x7f\\]", url): return "block"
    try: u = urlsplit(url)
    except ValueError: return "block"
    if u.scheme not in ("http", "https") or not u.netloc: return "block"
    if "@" in u.netloc: return "block"
    try: port = u.port
    except ValueError: return "block"
    if port not in (None, 80, 443): return "block"
    host = (u.hostname or "").rstrip(".").lower()
    if not host or not host.isascii(): return "block"
    if host in BLOCK_NAMES or host.endswith(BLOCK_SUFFIX): return "block"
    if ":" in host:
        try: return "block" if bad_ip(ipaddress.ip_address(host)) else "block"   # public IPv6 literals are refused by policy too
        except ValueError: return "block"
    ip = parse_v4_loose(host)
    if ip is not None: return "block"          # policy: IP literals are refused outright, names only
    if re.fullmatch(r"[0-9.xXa-fA-F]+", host) and re.search(r"\d", host.split(".")[-1]): return "block"
    return "allow"

def main():
    data = json.load(open(os.path.join(HERE, "ssrf-urls.json")))
    bad = 0; n = 0
    for c in data["cases"]:
        got = classify(c["url"]); n += 1
        want = {"block": "block", "allow": "allow", "block_if_resolves_private": "allow"}[c["expect"]]
        if got != want:
            bad += 1; print("MISMATCH", c["id"], c["name"], "got", got, "want", want)
    inj = json.load(open(os.path.join(HERE, "injection-corpus.json")))
    ids = [t["id"] for t in inj["texts"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 30, "injection corpus ids"
    assert set(inj["invariants"]) == {"I1", "I2", "I3", "I4", "I5", "I6"}
    print(f"ssrf cases checked: {n}, mismatches: {bad}; injection texts: {len(ids)}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
