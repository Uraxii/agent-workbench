"""agent-workbench pure-Python CLI package.

One module per subcommand, dispatched by cli.main. No bash, no `.sh`
shims, no `subprocess.run(["bash", ...])` anywhere: every subcommand is a
genuine Python port of the shell tool it replaces. Subcommands that have a
proven Python sibling to delegate to (the `kb` family -> scripts/kb-serve.py)
reuse it via cli.siblings rather than reimplementing logic; the four with no
Python sibling (hub, board, init-workspace, deploy) are direct
bash-to-Python rewrites.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
