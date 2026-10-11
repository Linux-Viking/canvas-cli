"""Local configuration.

The Canvas URL and aliases live in a JSON file in the user's home directory.
The API token lives only in the OS keyring (or the CANVAS_TOKEN environment
variable) and is deliberately never passed through the file helpers below.
"""

import json
import os
from urllib.parse import urlparse

import keyring
import keyring.errors

from .errors import ConfigError

CONFIG_FILE = os.path.expanduser("~/.canvas_cli.json")
SERVICE_NAME = "canvas_cli"
TOKEN_KEY = "api_token"  # noqa: S105 - keyring entry name, not a secret
TOKEN_ENV_VAR = "CANVAS_TOKEN"  # noqa: S105 - variable name, not a secret
DEFAULT_URL = "https://canvas.instructure.com"

# Keys that must never be written to the config file.
_FORBIDDEN_FILE_KEYS = {"token", TOKEN_KEY}


# --- Config file (URL + aliases only) ---


def _read_file():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"Could not read {CONFIG_FILE}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_FILE} is not a JSON object.")
    return data


def _write_file(data):
    """Atomically write the config file with owner-only permissions."""
    leaked = _FORBIDDEN_FILE_KEYS & data.keys()
    if leaked:
        # Guard against a future refactor accidentally persisting the token.
        raise ValueError(f"Refusing to write secret keys to config file: {sorted(leaked)}")

    tmp_path = f"{CONFIG_FILE}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def normalize_url(url):
    """Return a clean https:// base URL, or raise ConfigError.

    Accepts bare hostnames ("school.instructure.com") and strips trailing
    slashes. Plain http:// is rejected because the token is sent as a
    Bearer header on every request.
    """
    url = (url or "").strip()
    if not url:
        raise ConfigError("Canvas URL is empty.")
    if "://" not in url:
        url = f"https://{url}"

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ConfigError(
            f"Canvas URL must use https:// (got '{parsed.scheme}://'). "
            "Your API token would otherwise be sent unencrypted."
        )
    if not parsed.hostname:
        raise ConfigError(f"'{url}' is not a valid Canvas URL.")
    return f"https://{parsed.netloc}{parsed.path.rstrip('/')}"


def get_url():
    """Return the configured Canvas base URL (validated), or the default."""
    return normalize_url(_read_file().get("url", DEFAULT_URL))


def save_url(url):
    """Validate and store the Canvas URL, preserving existing aliases."""
    data = _read_file()
    data["url"] = normalize_url(url)
    _write_file(data)
    return data["url"]


def set_alias(name, target_id):
    """Sets an alias name to a target ID."""
    data = _read_file()
    data.setdefault("aliases", {})[name] = str(target_id)
    _write_file(data)


def get_aliases():
    return dict(_read_file().get("aliases", {}))


def resolve_alias(name_or_id):
    """Attempts to resolve a given string using the alias dictionary."""
    return get_aliases().get(str(name_or_id), str(name_or_id))


# --- Token (keyring / environment only) ---


def get_token():
    """Return the API token from $CANVAS_TOKEN or the OS keyring, or None."""
    env_token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if env_token:
        return env_token
    try:
        return keyring.get_password(SERVICE_NAME, TOKEN_KEY)
    except keyring.errors.KeyringError as e:
        raise ConfigError(
            f"Could not read the API token from the system keyring ({type(e).__name__}). "
            f"Set the {TOKEN_ENV_VAR} environment variable instead, or see the README's "
            "keyring troubleshooting section."
        ) from e


def set_token(token):
    try:
        keyring.set_password(SERVICE_NAME, TOKEN_KEY, token)
    except keyring.errors.KeyringError as e:
        raise ConfigError(
            f"Could not save the API token to the system keyring ({type(e).__name__}). "
            "See the README's keyring troubleshooting section."
        ) from e


def _backend_names(backend):
    """Yield fully qualified class names of a keyring backend and any it chains."""
    yield f"{type(backend).__module__}.{type(backend).__name__}"
    for child in getattr(backend, "backends", []) or []:
        yield from _backend_names(child)


def keyring_warning():
    """Return a warning string if the active keyring backend is insecure or missing."""
    names = list(_backend_names(keyring.get_keyring()))
    if any("Plaintext" in name for name in names):
        return (
            "Your keyring backend stores secrets in a plain-text file "
            f"({', '.join(names)}). Consider installing a secure backend "
            "(e.g. GNOME Keyring / KWallet) or using the CANVAS_TOKEN environment variable."
        )
    if all(name.startswith(("keyring.backends.fail", "keyring.backends.null")) for name in names):
        return (
            "No usable system keyring was found. Install one (e.g. GNOME Keyring / KWallet) "
            "or use the CANVAS_TOKEN environment variable."
        )
    return None
