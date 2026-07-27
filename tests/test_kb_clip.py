"""Tests for scripts/kb-clip.py -- URL-scheme allowlisting and SSRF
destination guard in fetch_html.

Verifies the H1 fix: file:// (and any non-http(s) scheme) is rejected
before urlopen is ever called, closing the local-file-read reachable via
the kb-serve /clip endpoint.

Also verifies the SSRF fix (ticket agent-workbench-h5u): fetch_html
resolves the hostname via DNS and rejects any URL whose resolved IP is
not public, on the initial URL AND on every redirect hop.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "kb-clip.py"


def _load_kb_clip():
    spec = importlib.util.spec_from_file_location("kb_clip_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kb_clip = _load_kb_clip()


@pytest.mark.parametrize(
    "url",
    ["file:///etc/hostname", "ftp://example.invalid/file", "/etc/hostname"],
)
def test_check_url_scheme_rejects_non_http(url: str) -> None:
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        kb_clip.check_url_scheme(url)


@pytest.mark.parametrize("url", ["http://example.invalid/page", "https://example.invalid/page"])
def test_check_url_scheme_allows_http_https(url: str) -> None:
    kb_clip.check_url_scheme(url)  # must not raise


def test_fetch_html_rejects_file_scheme_without_reaching_urlopen() -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(ValueError, match="unsupported URL scheme"):
            kb_clip.fetch_html("file:///etc/hostname")
    mock_urlopen.assert_not_called()


def test_build_note_path_reserves_atomically_past_a_preexisting_collision(tmp_path: Path) -> None:
    """TOCTOU fix: build_note_path reserves the winning filename via
    os.open(O_CREAT|O_EXCL) instead of a check-then-write .exists() probe,
    so two concurrent callers racing on the same slug can never both win.

    A naive `if candidate.exists(): n += 1` reimplementation would still
    pick the same "slug-2.md" path here (the string-level result looks
    identical), so this only goes red on the property a check-then-write
    reimplementation cannot provide: the returned path is already reserved
    (0 bytes, on disk) the instant build_note_path returns, before the
    caller ever calls write_text().
    """
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "slug.md").write_text("existing note", encoding="utf-8")

    result = kb_clip.build_note_path(sources_dir, "slug")

    assert result == sources_dir / "slug-2.md"
    assert result.exists()
    assert result.stat().st_size == 0


def _addrinfo(ip: str) -> list[tuple]:
    """One socket.getaddrinfo() result tuple for a given IPv4/IPv6 literal,
    shaped like the real stdlib return value."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
    return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]


@pytest.mark.parametrize(
    "resolved_ip",
    [
        "127.0.0.1",  # loopback
        "169.254.169.254",  # cloud metadata / link-local
        "10.0.0.5",  # private LAN
        "192.168.1.1",  # private LAN
        "::1",  # IPv6 loopback
        "100.64.0.1",  # Tailscale / CGNAT
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 loopback
        "::ffff:169.254.169.254",  # IPv4-mapped IPv6 cloud metadata
    ],
)
def test_check_destination_is_public_rejects_non_public_ip(resolved_ip: str) -> None:
    """Regression guard: IPv4-mapped IPv6 (::ffff:x.x.x.x) cases silently
    reopen this hole on a Python-runtime downgrade below 3.13, where
    ipaddress.IPv6Address.is_global did not yet delegate to the embedded
    IPv4 address."""
    with patch("socket.getaddrinfo", return_value=_addrinfo(resolved_ip)):
        with pytest.raises(ValueError, match="non-public address"):
            kb_clip.check_destination_is_public("http://target.example/page")


@pytest.mark.parametrize(
    "host",
    [
        "2130706433",  # decimal encoding of 127.0.0.1
        "0177.0.0.1",  # octal encoding of 127.0.0.1
    ],
)
def test_check_destination_is_public_rejects_encoded_ipv4_loopback(host: str) -> None:
    """getaddrinfo normalizes decimal/octal IPv4 literals to their dotted
    form (127.0.0.1 here), so the guard must still reject the resolved
    address even though the hostname in the URL doesn't look like
    loopback."""
    with patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        with pytest.raises(ValueError, match="non-public address"):
            kb_clip.check_destination_is_public(f"http://{host}/page")


def test_check_destination_is_public_rejects_localhost_hostname() -> None:
    with patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        with pytest.raises(ValueError, match="non-public address"):
            kb_clip.check_destination_is_public("http://localhost/page")


def test_check_destination_is_public_rejects_public_hostname_resolving_to_loopback() -> None:
    """The DNS-normalization case: a hostname that LOOKS public but its
    DNS record points at loopback (attacker-controlled DNS rebinding)."""
    with patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        with pytest.raises(ValueError, match="non-public address"):
            kb_clip.check_destination_is_public("http://sneaky.example.invalid/page")


def test_check_destination_is_public_allows_public_ip() -> None:
    with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        kb_clip.check_destination_is_public("http://example.invalid/page")  # must not raise


def test_redirect_handler_rejects_redirect_to_internal_target() -> None:
    handler = kb_clip._DestinationCheckingRedirectHandler()
    with patch("socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
        with pytest.raises(ValueError, match="non-public address"):
            handler.redirect_request(
                MagicMock(), None, 302, "Found", MagicMock(),
                "http://169.254.169.254/latest/meta-data/",
            )


def test_redirect_handler_rejects_redirect_to_non_http_scheme() -> None:
    """Ticket agent-workbench-5ov: a redirect hop to a non-http(s) scheme
    (e.g. file://) must be rejected by the scheme check before the
    destination check or the redirect is ever followed."""
    handler = kb_clip._DestinationCheckingRedirectHandler()
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        handler.redirect_request(
            MagicMock(), None, 302, "Found", MagicMock(),
            "file:///etc/passwd",
        )


def test_fetch_html_rejects_non_public_destination_without_reaching_urlopen() -> None:
    with patch("socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        with patch("urllib.request.urlopen") as mock_urlopen:
            with pytest.raises(ValueError, match="non-public address"):
                kb_clip.fetch_html("http://localhost/page")
        mock_urlopen.assert_not_called()


def test_fetch_html_allows_public_destination(tmp_path: Path) -> None:
    """Full happy path: public destination resolves, the actual network
    fetch is mocked so no real request goes out."""
    fake_response = MagicMock()
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False
    fake_response.read.return_value = b"<html>ok</html>"
    fake_response.headers.get_content_charset.return_value = "utf-8"
    fake_opener = MagicMock()
    fake_opener.open.return_value = fake_response

    with patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        with patch("urllib.request.build_opener", return_value=fake_opener):
            result = kb_clip.fetch_html("http://example.invalid/page")

    assert result == "<html>ok</html>"
