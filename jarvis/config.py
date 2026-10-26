"""Settings and secrets.

Non-secret settings live in ~/.jarvis/settings.json.
Secrets (AI key) live in the macOS Keychain via `keyring`. If no keychain is
available (e.g. Linux without a secret service) they fall back to
~/.jarvis/secrets.json with owner-only permissions.
"""
import copy
import json
import os
from pathlib import Path

HOME = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
HOME.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = HOME / "settings.json"
SECRETS_FILE = HOME / "secrets.json"
KEYRING_SERVICE = "jarvis-assistant"

DEFAULTS = {
    "name": "Vanshika",
    "timezone": "America/Edmonton",
    "work_start": "09:00",
    "work_end": "17:00",
    "brief_time": "06:30",
    "brief_email": False,          # also email the brief to yourself through Outlook
    "followup_days": 3,            # nudge after this many days without a reply
    "vips": [],                    # email addresses that always count as "needs you"
    "ai": {
        # "anthropic" = Anthropic Messages API format (Anthropic, or a gateway such as ICA that speaks it)
        # "openai"    = OpenAI chat/completions format (many gateways, including some ICA endpoints)
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "",
        "auth": "x-api-key",       # or "bearer" for gateways that want Authorization: Bearer <key>
    },
    "email": "",                   # your work address; only used to email the morning brief to yourself
    "gmail": {"address": ""},      # personal Gmail (App Password and calendar link live in the Keychain)
    "outlook": {
        "mode": "mac",             # "mac" = the Outlook app on this Mac (no registration); "graph" = Microsoft Graph
        "client_id": "",           # from your Azure / Entra app registration
        "tenant": "organizations", # or your tenant id / domain, e.g. ibm.onmicrosoft.com
    },
    "drop_folder": str(Path(os.environ.get("JARVIS_DROP", Path.home() / "Jarvis" / "IBM Drop"))),
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def settings():
    if SETTINGS_FILE.exists():
        try:
            return _merge(DEFAULTS, json.loads(SETTINGS_FILE.read_text()))
        except json.JSONDecodeError:
            pass
    return copy.deepcopy(DEFAULTS)


def save_settings(patch):
    current = settings()
    new = _merge(current, patch)
    SETTINGS_FILE.write_text(json.dumps(new, indent=2))
    return new


def drop_folder():
    p = Path(os.path.expanduser(settings()["drop_folder"]))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- secrets ----------
def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _file_secrets():
    if SECRETS_FILE.exists():
        return json.loads(SECRETS_FILE.read_text())
    return {}


def get_secret(name):
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(KEYRING_SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    return _file_secrets().get(name) or os.environ.get("JARVIS_" + name.upper())


def set_secret(name, value):
    kr = _keyring()
    if kr:
        try:
            if value:
                kr.set_password(KEYRING_SERVICE, name, value)
            else:
                try:
                    kr.delete_password(KEYRING_SERVICE, name)
                except Exception:
                    pass
            return "keychain"
        except Exception:
            pass
    data = _file_secrets()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    SECRETS_FILE.write_text(json.dumps(data))
    os.chmod(SECRETS_FILE, 0o600)
    return "file"


def has_secret(name):
    return bool(get_secret(name))
