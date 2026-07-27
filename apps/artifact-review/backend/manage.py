#!/usr/bin/env python3
"""Django management entrypoint for the artifact review backend."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Run Django administrative commands."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "artifact_review_site.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
