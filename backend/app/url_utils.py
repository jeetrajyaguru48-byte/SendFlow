from __future__ import annotations

from ipaddress import ip_address
from typing import Optional
from urllib.parse import urlparse


def _is_private_hostname(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost", "0.0.0.0"}:
        return True
    if host.endswith(".local"):
        return True
    if host == "::1":
        return True
    try:
        ip = ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except Exception:
        # Not an IP literal.
        return False


def is_public_https_url(url: Optional[str]) -> bool:
    """True only for https:// URLs with a public hostname (not localhost/private IP)."""
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        return False
    hostname = parsed.hostname or ""
    if _is_private_hostname(hostname):
        return False
    return True

