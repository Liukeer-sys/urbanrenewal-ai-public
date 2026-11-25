"""Select the offline deployment mode without loading AI dependencies."""

import os
from pathlib import Path


class PublicDemoError(ValueError):
    """A stable, safe-to-log reason for refusing demo egress."""


def public_demo_enabled():
    switch = os.environ.get("PUBLIC_DEMO_MODE", "").strip().lower()
    local_rag_module = Path(__file__).with_name("structured_rag.py")
    return switch in {"1", "true", "yes", "on"} or not local_rag_module.is_file()
