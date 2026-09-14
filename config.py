"""Judge-route resolution and user config — the single source of truth.

Priority chain (per field; base_url and api_key resolve independently so an
explicit route can still reuse the shell's key, the way the launchers do):

    1. CLI flag (--base-url)          — caller-side, applied by the CLIs
    2. SIDEEYE_JUDGE_BASE_URL / SIDEEYE_JUDGE_API_KEY   (explicit override)
    3. config file                    ($SIDEEYE_CONFIG or ~/.config/sideeye/config.json)
    4. ambient ANTHROPIC_*            (Claude Code's own route, or direct api key)

Config file shape (all keys optional; unknown keys ignored):

    {
      "judge": {
        "base_url": "https://…",           # real Claude route
        "api_key": "sk-…",                 # file should be chmod 600
        "trust_ambient_route": false       # let ambient ANTHROPIC_* pass the guard
      }
    }

base_url is optional: a key alone (config, SIDEEYE_JUDGE_*, or a bare
ANTHROPIC_API_KEY) means "talk to Anthropic direct" (api.anthropic.com) —
the common case for a user who has an API key and no gateway.

THE RULE this module enforces: the judge must never silently share the session's
cheap-model route. If the route came from the ambient ANTHROPIC_* (case 4 — the
same vars a Qwen/GLM session runs on), it must be a real Anthropic host or the
user must have said so explicitly via trust_ambient_route.
"""
from __future__ import annotations

import ipaddress
import json
import os
import pathlib
from urllib.parse import urlparse

AMBIENT_BASE_DEFAULT = "https://api.anthropic.com"


def config_path() -> pathlib.Path:
    return pathlib.Path(
        os.environ.get("SIDEEYE_CONFIG")
        or pathlib.Path.home() / ".config" / "sideeye" / "config.json"
    )


def load_config(path=None) -> dict:
    """Read the config file; missing/unreadable/invalid is treated as empty.

    A broken config file must not brick the CLI — the caller's route errors
    already explain every other way to configure. Never log the contents.
    """
    p = pathlib.Path(path) if path else config_path()
    try:
        with open(p) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_judge_route(config=None):
    """Return (base_url, api_key, source) for the judge.

    source is the layer base_url resolved from: "env" | "config" | "ambient" |
    None (nothing configured). The key resolves through the same chain so an
    explicit base + ambient key still works (the old two-or-chains semantics).
    """
    cfg = (config if config is not None else load_config()).get("judge", {})

    env_base, env_key = (os.environ.get("SIDEEYE_JUDGE_BASE_URL"),
                         os.environ.get("SIDEEYE_JUDGE_API_KEY"))
    cfg_base, cfg_key = cfg.get("base_url"), cfg.get("api_key")
    amb_base = os.environ.get("ANTHROPIC_BASE_URL")
    amb_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")

    if env_base:
        base, source = env_base, "env"
    elif cfg_base:
        base, source = cfg_base, "config"
    elif amb_base:
        base, source = amb_base, "ambient"
    elif env_key or cfg_key:
        # A key with no base anywhere means "talk to Anthropic direct" — a
        # real Claude route, and the common case for a user who has an API
        # key and no gateway. Source follows the key's own layer.
        base, source = AMBIENT_BASE_DEFAULT, "env" if env_key else "config"
    elif amb_key:
        # A bare ANTHROPIC_API_KEY with no base: same default, ambient source.
        base, source = AMBIENT_BASE_DEFAULT, "ambient"
    else:
        base, source = None, None

    key = env_key or cfg_key or amb_key
    return base, key, source


def trust_ambient_route(config=None) -> bool:
    cfg = (config if config is not None else load_config()).get("judge", {})
    return bool(cfg.get("trust_ambient_route"))


def _host(base_url: str):
    try:
        return urlparse(base_url).hostname
    except ValueError:
        return None


def _is_anthropic_host(host) -> bool:
    return host == "api.anthropic.com" or (host or "").endswith(".anthropic.com")


def _is_local_host(host) -> bool:
    if host in (None, "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def ambient_route_warning(base_url) -> str | None:
    """Why an ambient route may not be trusted as the judge route, else None."""
    host = _host(base_url or "")
    if _is_anthropic_host(host):
        return None
    where = "is a local/private address" if _is_local_host(host) else "is not an Anthropic host"
    return (
        f"the ambient ANTHROPIC route ({base_url}) {where} — that is likely this "
        "session's own (cheap) model, and a judge sharing the drafted-with model "
        "defeats Side-Eye. Point SIDEEYE_JUDGE_BASE_URL (or judge.base_url in "
        f"{config_path()}) at the real Claude route, or set "
        '"judge": {"trust_ambient_route": true} if this route really does serve Claude.'
    )


class RouteError(Exception):
    """No usable judge route — not configured, or blocked by a guard."""


def require_judge_route(flag_base=None):
    """Resolve AND validate the judge route; return (base, key, source).

    Raises RouteError with an operator-actionable message. The ambient layer
    must additionally pass the Anthropic-host / explicit-trust check: a
    session's own cheap route is by definition ambient, so self-grading is
    only reachable by the user saying so (trust_ambient_route).
    """
    # Lazy import: judge.py imports this module at load time.
    from sideeye.judge.judge import judge_route_guard

    base, key, source = resolve_judge_route()
    if flag_base:
        base, source = flag_base, "flag"
    if not base or not key:
        raise RouteError(ROUTE_HELP)
    if prob := judge_route_guard(base):
        raise RouteError(prob)
    if source == "ambient" and not trust_ambient_route():
        if warn := ambient_route_warning(base):
            raise RouteError(warn)
    return base, key, source


ROUTE_HELP = (
    "no judge route configured. Any one of:\n"
    f"  config file {config_path()}  —  {{\"judge\": {{\"api_key\": \"sk-…\"}}}} "
    "(base_url optional: a key alone means direct api.anthropic.com)\n"
    "  SIDEEYE_JUDGE_API_KEY (direct api.anthropic.com), or "
    "SIDEEYE_JUDGE_BASE_URL + SIDEEYE_JUDGE_API_KEY (a gateway that serves Claude)\n"
    "  ANTHROPIC_API_KEY (direct api.anthropic.com) or ANTHROPIC_BASE_URL + "
    "ANTHROPIC_AUTH_TOKEN (a gateway that really serves Claude)"
)


def describe_route():
    """Human-readable route report for `sideeye route`. Never contains a secret.

    Returns (text, ok). Runs the exact resolution + guards the CLIs use, so
    what this prints is what a review would actually do (it spends nothing).
    """
    base, key, source = resolve_judge_route()
    lines = [
        f"route:   {base or '(unset)'}   [from {source or 'nowhere'}]",
        f"key:     {'set' if key else 'MISSING'}",
    ]
    if not base or not key:
        lines.append(ROUTE_HELP)
        return "\n".join(lines), False
    try:
        require_judge_route()
    except RouteError as e:
        lines.append(f"verdict: BLOCKED — {e}")
        return "\n".join(lines), False
    lines.append("verdict: OK — judge may use this route")
    return "\n".join(lines), True
