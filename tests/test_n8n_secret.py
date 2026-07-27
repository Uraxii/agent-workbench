"""Tests for scripts/n8n-container/n8n-secret.py -- the standalone n8n
secret resolver (encryption key + Public API key), symmetric to
kb-serve.py's load_kb_env / resolve_api_key / cmd_resolve_secret trio.

Everything runs offline: subprocess.run is monkeypatched wherever a vault
CLI command would otherwise be shelled out to, and every config lives
under tmp_path, never the real ~/.local/share/n8n.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "n8n-container" / "n8n-secret.py"
)


def _load_n8n_secret():
    spec = importlib.util.spec_from_file_location("n8n_secret_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


n8n_secret = _load_n8n_secret()


# ═══════════════════════════════════════════════════════════════════════
# resolve_encryption_key
# ═══════════════════════════════════════════════════════════════════════


def test_resolve_encryption_key_cmd_wins_over_static_when_both_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        n8n_secret.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout="from-vault\n"),
    )
    env = {"N8N_ENCRYPTION_KEY_CMD": "pass-cli item view foo", "N8N_ENCRYPTION_KEY": "static-value"}
    assert n8n_secret.resolve_encryption_key(env) == "from-vault"


def test_resolve_encryption_key_uses_static_value_when_no_cmd() -> None:
    env = {"N8N_ENCRYPTION_KEY": "static-value"}
    assert n8n_secret.resolve_encryption_key(env) == "static-value"


def test_resolve_encryption_key_none_when_neither_set() -> None:
    assert n8n_secret.resolve_encryption_key({}) is None


def test_resolve_encryption_key_cmd_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*a, **kw):
        raise subprocess.CalledProcessError(1, "cmd")

    monkeypatch.setattr(n8n_secret.subprocess, "run", fake_run)
    env = {"N8N_ENCRYPTION_KEY_CMD": "broken-cmd"}
    assert n8n_secret.resolve_encryption_key(env) is None


# ═══════════════════════════════════════════════════════════════════════
# resolve_api_key (symmetric to resolve_encryption_key)
# ═══════════════════════════════════════════════════════════════════════


def test_resolve_api_key_cmd_wins_over_static_when_both_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        n8n_secret.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout="api-from-vault\n"),
    )
    env = {"N8N_API_KEY_CMD": "pass-cli item view bar", "N8N_API_KEY": "static-api-value"}
    assert n8n_secret.resolve_api_key(env) == "api-from-vault"


def test_resolve_api_key_uses_static_value_when_no_cmd() -> None:
    env = {"N8N_API_KEY": "static-api-value"}
    assert n8n_secret.resolve_api_key(env) == "static-api-value"


def test_resolve_api_key_none_when_neither_set() -> None:
    assert n8n_secret.resolve_api_key({}) is None


def test_resolve_api_key_cmd_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired("cmd", 15)

    monkeypatch.setattr(n8n_secret.subprocess, "run", fake_run)
    env = {"N8N_API_KEY_CMD": "slow-cmd"}
    assert n8n_secret.resolve_api_key(env) is None


# ═══════════════════════════════════════════════════════════════════════
# cmd_resolve_secret
# ═══════════════════════════════════════════════════════════════════════


def test_cmd_resolve_secret_prints_key_line_when_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("N8N_ENCRYPTION_KEY", "resolved-key")
    args = argparse.Namespace(data_dir=tmp_path)
    assert n8n_secret.cmd_resolve_secret(args) == 0
    assert capsys.readouterr().out == "N8N_ENCRYPTION_KEY=resolved-key\n"


def test_cmd_resolve_secret_prints_empty_value_and_returns_0_when_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Loud failure happens at n8n startup, not here -- an unset key still
    exits 0 with the key printed empty."""
    monkeypatch.delenv("N8N_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("N8N_ENCRYPTION_KEY_CMD", raising=False)
    args = argparse.Namespace(data_dir=tmp_path)
    assert n8n_secret.cmd_resolve_secret(args) == 0
    assert capsys.readouterr().out == "N8N_ENCRYPTION_KEY=\n"


# ═══════════════════════════════════════════════════════════════════════
# cmd_resolve_api_key
# ═══════════════════════════════════════════════════════════════════════


def test_cmd_resolve_api_key_prints_raw_key_and_returns_0_when_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("N8N_API_KEY", "raw-key-value")
    args = argparse.Namespace(data_dir=tmp_path)
    assert n8n_secret.cmd_resolve_api_key(args) == 0
    assert capsys.readouterr().out == "raw-key-value\n"


def test_cmd_resolve_api_key_fails_loudly_when_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Unlike cmd_resolve_secret, there is no n8n-startup safety net here --
    this CLI must fail loudly itself: exit 1, stderr message."""
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    monkeypatch.delenv("N8N_API_KEY_CMD", raising=False)
    args = argparse.Namespace(data_dir=tmp_path)
    assert n8n_secret.cmd_resolve_api_key(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no N8N_API_KEY / N8N_API_KEY_CMD resolved" in captured.err


# ═══════════════════════════════════════════════════════════════════════
# load_n8n_env
# ═══════════════════════════════════════════════════════════════════════


def test_load_n8n_env_parses_simple_key_value_lines(tmp_path: Path) -> None:
    (tmp_path / "n8n.env").write_text(
        "\n".join([
            "# a comment",
            "",
            "N8N_ENCRYPTION_KEY=abc123",
            '  N8N_API_KEY="quoted-value"  ',
            "N8N_API_KEY_CMD='single-quoted'",
        ]),
        encoding="utf-8",
    )
    values = n8n_secret.load_n8n_env(tmp_path)
    assert values == {
        "N8N_ENCRYPTION_KEY": "abc123",
        "N8N_API_KEY": "quoted-value",
        "N8N_API_KEY_CMD": "single-quoted",
    }


def test_load_n8n_env_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    assert n8n_secret.load_n8n_env(tmp_path) == {}
