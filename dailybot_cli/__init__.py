"""Dailybot CLI - The command-line bridge between humans and agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("dailybot-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"
