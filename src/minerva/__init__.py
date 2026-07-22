"""Minerva's local-first research core."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("minerva-research")
except PackageNotFoundError:  # pragma: no cover - source tree without installation
    __version__ = "0.1.0a1"

__all__ = ["__version__"]
