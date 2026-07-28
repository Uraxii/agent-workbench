"""Fail closed for any future server-side url fetch."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from django.http import HttpRequest

REMOTE_FETCH_FIELDS = frozenset({"fetch_url", "remote", "src_url", "url"})


class RemoteFetchRejected(ValueError):
    """Raised when a request asks the server to fetch remote content."""


def reject_remote_fetch(request: HttpRequest) -> None:
    """Reject requests carrying fields that ask the server to fetch content."""
    fields = set(request.GET)
    if request.method in {"POST", "PUT", "PATCH"}:
        fields.update(request.POST)
    if fields & REMOTE_FETCH_FIELDS:
        raise RemoteFetchRejected("remote_fetch_rejected")


def assert_local_url(url: str) -> None:
    """Allow only explicit loopback literal URLs."""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise RemoteFetchRejected("non_loopback_url")
    try:
        address = ipaddress.ip_address(parsed_url.hostname)
    except ValueError as exc:
        raise RemoteFetchRejected("non_loopback_url") from exc
    if not address.is_loopback:
        raise RemoteFetchRejected("non_loopback_url")


__all__ = ["REMOTE_FETCH_FIELDS", "RemoteFetchRejected", "assert_local_url", "reject_remote_fetch"]
