"""Exception types shown to the user.

All of them subclass click.ClickException, so Click prints "Error: <message>"
and exits with a non-zero status without any per-command handling.
"""

import click


class CanvasCliError(click.ClickException):
    """Base class for all expected, user-facing errors."""


class ConfigError(CanvasCliError):
    """Missing or invalid local configuration (URL, keyring, config file)."""


class CanvasError(CanvasCliError):
    """A request to the Canvas API failed."""


class AuthError(CanvasError):
    """The API token is missing, invalid, expired, or revoked."""


class RateLimitError(CanvasError):
    """Canvas kept throttling us after all retries were used."""
