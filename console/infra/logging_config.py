"""
Project Console — logging.
One place to configure format/level; every module gets its logger via get_logger(__name__).
Level is overridable with $CONSOLE_LOG_LEVEL (DEBUG/INFO/WARNING/...).
"""
import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
_configured = False


def _configure_root():
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger("console")
    root.addHandler(handler)
    root.setLevel(os.environ.get("CONSOLE_LOG_LEVEL", "INFO").upper())
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the 'console' root (configured once)."""
    _configure_root()
    short = name.split(".")[-1] if name else "console"
    return logging.getLogger(f"console.{short}")
