"""agent-workbench pure-Python CLI package.

One module per subcommand, dispatched by cli.main. No bash, no `.sh`
shims, no `subprocess.run(["bash", ...])` anywhere: every subcommand is a
genuine Python port of the shell tool it replaces. Subcommands that have a
proven Python sibling to delegate to (the `kb` family -> scripts/kb-svc.py)
reuse it via cli.siblings rather than reimplementing logic.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
