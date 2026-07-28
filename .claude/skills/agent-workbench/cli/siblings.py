"""Load hyphenated sibling scripts as importable modules.

Some repo scripts have hyphenated filenames a normal ``import``
statement cannot address, so this loads them by path
(importlib.util.spec_from_file_location, registered in sys.modules BEFORE
exec so dataclass annotation resolution works).

Note what is NOT here: the `kb` subcommand does not load kb-serve.py, and
the `artifact` subcommand does not load an artifact server. Each service
owns its own data and the CLI reaches it over HTTP, so an in-process
loader would be a second way into the same files.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from cli.paths import SCRIPTS_DIR

__all__ = ["load_script", "load_module_at"]


def load_module_at(path: Path, module_name: str) -> types.ModuleType:
    """Import the script at ``path`` as a module named ``module_name``.

    Postconditions: the module is registered in ``sys.modules`` under
    ``module_name`` before its body executes (required so any
    ``@dataclass`` inside it resolves annotations).
    Raises:
        ImportError: if the file cannot be located or loaded.
    """
    if not path.is_file():
        raise ImportError(f"no such sibling script: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_script(name: str) -> types.ModuleType:
    """Import ``<repo>/scripts/<name>.py`` as a module by path.

    Args:
        name: hyphenated script stem, e.g. ``"kb-index"``.

    Returns:
        The executed module object.

    Preconditions: ``<repo>/scripts/<name>.py`` exists.
    """
    # A handful of siblings import a same-dir module by its plain
    # underscored name, which only resolves if SCRIPTS_DIR is on
    # sys.path. Adding it once here keeps that working without every
    # sibling needing its own path shim.
    scripts_dir = str(SCRIPTS_DIR)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return load_module_at(SCRIPTS_DIR / f"{name}.py", name.replace("-", "_"))
