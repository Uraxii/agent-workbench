"""Load hyphenated sibling scripts as importable modules.

The `kb` subcommand is a thin facade over the existing, proven
``scripts/kb-serve.py`` (which itself facades kb-index.py / kb-clip.py /
kb-atomize.py). Those files have hyphenated names a normal ``import``
cannot address, so this reuses kb-serve.py's own proven load-by-path
pattern (importlib.util.spec_from_file_location, register in sys.modules
BEFORE exec so dataclass annotation resolution works). This is deliberate
reuse, not a rewrite: the deterministic clip/put/query/atomize logic and
the http/https scheme allowlist (kb-clip.check_url_scheme) are inherited
verbatim, never reimplemented here.
"""
from __future__ import annotations

import importlib.util
import sys
import types

from cli.paths import SCRIPTS_DIR

__all__ = ["load_script", "load_kb_serve"]


def load_script(name: str) -> types.ModuleType:
    """Import ``<repo>/scripts/<name>.py`` as a module by path.

    Args:
        name: hyphenated script stem, e.g. ``"kb-serve"``.

    Returns:
        The executed module object.

    Preconditions: ``<repo>/scripts/<name>.py`` exists.
    Postconditions: the module is registered in ``sys.modules`` under its
        underscored name before its body executes (required so any
        ``@dataclass`` inside it resolves annotations).
    Raises:
        ImportError: if the file cannot be located or loaded.
    """
    path = SCRIPTS_DIR / f"{name}.py"
    if not path.is_file():
        raise ImportError(f"no such sibling script: {path}")

    # A handful of siblings (e.g. build-kb-index.py -> kb_embeddings)
    # import a same-dir module by its plain underscored name, which only
    # resolves if SCRIPTS_DIR is on sys.path. Adding it once here keeps
    # that working without every sibling needing its own path shim.
    scripts_dir = str(SCRIPTS_DIR)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    module_name = name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_kb_serve() -> types.ModuleType:
    """Load ``scripts/kb-serve.py`` (the in-process fallback target).

    Returns:
        The kb-serve module, exposing kb_put / kb_clip_and_atomize /
        run_query / resolve_kb_home-backed helpers the `kb` port calls
        when the HTTP service is down.
    """
    return load_script("kb-serve")
