"""agent-workbench pure-Python CLI package.

One module per subcommand, dispatched by cli.main. No bash, no `.sh`
shims, no `subprocess.run(["bash", ...])` anywhere: every subcommand is a
genuine Python port of the shell tool it replaces. Each data subcommand
(kb, bd, artifact) is an HTTP client of its respective service. The service
owns the data and the filesystem; nothing in the CLI touches data files
directly.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
