"""Runtime configuration for the knowledgebase service.

Holds the one resolved config object every kb service module reads, plus
the loader for hyphenated sibling scripts (kb-index.py / kb-clip.py /
kb-atomize.py), whose filenames a normal `import` statement cannot name.

Everything here is read at startup from the process environment, merged
under the optional `<kb_home>/kb.env` file (the real environment wins).
None of it is reachable from an HTTP request.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_ATOMIZE_MODEL",
    "DEFAULT_LLM_BASE_URL",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_PORT",
    "KbServeConfig",
    "build_config",
    "load_kb_env",
    "load_sibling",
    "resolve_api_key",
    "resolve_kb_home",
]

log = logging.getLogger("kb-serve")

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_PORT = 9100
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"
# A capable general-purpose model: atomize's decontextualization and
# section granularity need to stay reliable. Override via
# KB_ATOMIZE_MODEL for a cheaper tier.
DEFAULT_ATOMIZE_MODEL = "anthropic/claude-sonnet-4.5"
API_KEY_CMD_TIMEOUT_SEC = 15.0


def load_sibling(name: str) -> types.ModuleType:
    """Import a hyphenated sibling script (e.g. "kb-index") as a module.

    Registers the module in ``sys.modules`` before executing it, which
    ``@dataclass`` inside those scripts requires for annotation lookup.
    """
    path = SCRIPT_DIR / f"{name}.py"
    module_name = name.replace("-", "_")
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_kb_home(explicit: str | None) -> Path:
    """Vault root: explicit value, else $KB_HOME, else ~/.knowledgebase."""
    if explicit:
        return Path(explicit)
    env_value = os.environ.get("KB_HOME")
    return Path(env_value) if env_value else Path.home() / ".knowledgebase"


@dataclass(frozen=True)
class KbServeConfig:
    """Resolved runtime config for one server or CLI invocation."""

    kb_home: Path
    enrich_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None
    atomize_model: str = DEFAULT_ATOMIZE_MODEL
    embed_model: str | None = None


def load_kb_env(kb_home: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines from ``<kb_home>/kb.env``.

    Missing file, blank lines and '#' comments are skipped; never raises.
    Values may be wrapped in matching quotes, nothing fancier.
    """
    env_path = kb_home / "kb.env"
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_api_key(env: Mapping[str, str]) -> str | None:
    """Resolve the LLM API key from operator config.

    ``KB_LLM_API_KEY_CMD`` (a vault CLI command whose stdout is the key)
    wins over a static ``KB_LLM_API_KEY`` when it succeeds with a
    non-empty result; otherwise the static value is used. Returns None if
    neither yields one. Never logs the resolved value.

    SECURITY: this is the one shell execution in the service, and its
    input is operator config (process env or the gitignored kb.env), not
    anything reachable from an HTTP request. No request handler can write
    kb.env: every vault write lands under
    ``<kb_home>/<project>/<type dir>/<slug>.md``.
    """
    static_key = env.get("KB_LLM_API_KEY", "").strip() or None
    command = env.get("KB_LLM_API_KEY_CMD", "").strip()
    if not command:
        return static_key
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=API_KEY_CMD_TIMEOUT_SEC, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("KB_LLM_API_KEY_CMD failed (%s); no key resolved", exc)
        return static_key
    return result.stdout.strip() or static_key


def build_config(kb_home: Path) -> KbServeConfig:
    """Merge kb.env under the process env (env wins) and resolve keys."""
    merged: dict[str, str] = {**load_kb_env(kb_home), **os.environ}
    enrich_enabled = merged.get("KB_ENRICH", "0") == "1"
    embed_model = merged.get("KB_EMBED_MODEL", "").strip() or None
    needs_key = enrich_enabled or embed_model is not None
    api_key = resolve_api_key(merged) if needs_key else None
    atomize_model = merged.get("KB_ATOMIZE_MODEL", "").strip()
    return KbServeConfig(
        kb_home=kb_home,
        enrich_enabled=enrich_enabled,
        llm_base_url=merged.get("KB_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_model=merged.get("KB_LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_api_key=api_key,
        atomize_model=atomize_model or DEFAULT_ATOMIZE_MODEL,
        embed_model=embed_model,
    )
