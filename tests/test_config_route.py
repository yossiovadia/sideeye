"""Judge-route resolution chain + cheap-route guards — offline, no network.

Every test isolates both config layers: SIDEEYE_JUDGE_*/ANTHROPIC_* env vars
and SIDEEYE_CONFIG (pointed at a nonexistent file unless the test writes one).
"""
import json

import pytest

from sideeye import config as C


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for var in ("SIDEEYE_JUDGE_BASE_URL", "SIDEEYE_JUDGE_API_KEY",
                "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SIDEEYE_CONFIG", str(tmp_path / "absent-config.json"))


def write_config(tmp_path, monkeypatch, judge: dict):
    p = tmp_path / "sideeye-config.json"
    p.write_text(json.dumps({"judge": judge}))
    monkeypatch.setenv("SIDEEYE_CONFIG", str(p))
    return p


# --- resolution chain -------------------------------------------------------

def test_nothing_configured_resolves_to_none(monkeypatch):
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == (None, None, None)
    with pytest.raises(C.RouteError):
        C.require_judge_route()


def test_env_wins_over_config_and_ambient(monkeypatch, tmp_path):
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "https://explicit.example")
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "explicit-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ambient.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-key")
    write_config(tmp_path, monkeypatch,
                 {"base_url": "https://cfg.example", "api_key": "cfg-key"})
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == ("https://explicit.example", "explicit-key", "env")


def test_config_wins_over_ambient(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ambient.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-key")
    write_config(tmp_path, monkeypatch,
                 {"base_url": "https://cfg.example", "api_key": "cfg-key"})
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == ("https://cfg.example", "cfg-key", "config")


def test_ambient_auth_token_and_explicit_base(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == ("https://gateway.example", "tok", "ambient")


def test_bare_api_key_defaults_to_direct_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    base, key, source = C.resolve_judge_route()
    assert (base, source) == (C.AMBIENT_BASE_DEFAULT, "ambient")
    # direct Anthropic is a real Claude route — no trust opt-in needed
    assert C.require_judge_route()[0] == C.AMBIENT_BASE_DEFAULT


def test_config_key_only_defaults_to_direct_anthropic(monkeypatch, tmp_path):
    write_config(tmp_path, monkeypatch, {"api_key": "sk-cfg-only"})
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == (C.AMBIENT_BASE_DEFAULT, "sk-cfg-only", "config")
    # direct Anthropic is a real Claude route — no trust opt-in needed
    assert C.require_judge_route()[0] == C.AMBIENT_BASE_DEFAULT


def test_env_key_only_defaults_to_direct_anthropic(monkeypatch):
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "sk-env-only")
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == (C.AMBIENT_BASE_DEFAULT, "sk-env-only", "env")
    assert C.require_judge_route()[0] == C.AMBIENT_BASE_DEFAULT


def test_key_only_default_does_not_shadow_ambient_base(monkeypatch, tmp_path):
    # an ambient base still wins over the key-alone default — a dogfood
    # session with a gateway base + explicit sideeye key must stay blocked
    # (trust_ambient_route), not silently retargeted at api.anthropic.com
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://10.0.0.5:8000")
    write_config(tmp_path, monkeypatch, {"api_key": "sk-cfg"})
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == ("http://10.0.0.5:8000", "sk-cfg", "ambient")
    with pytest.raises(C.RouteError, match="trust_ambient_route"):
        C.require_judge_route()


def test_cross_layer_key_reuse_keeps_old_semantics(monkeypatch):
    # explicit base + ambient key: the launchers rely on per-field precedence
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "https://explicit.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ambient")
    base, key, source = C.resolve_judge_route()
    assert (base, key, source) == ("https://explicit.example", "sk-ambient", "env")


def test_invalid_config_file_is_ignored(monkeypatch, tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    monkeypatch.setenv("SIDEEYE_CONFIG", str(p))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ambient")
    base, _, source = C.resolve_judge_route()
    assert source == "ambient"  # fell through the broken config, no crash


def test_flag_overrides_everything(monkeypatch):
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "https://explicit.example")
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "k")
    base, _, source = C.require_judge_route("https://flag.example")
    assert (base, source) == ("https://flag.example", "flag")


# --- guards -----------------------------------------------------------------

def test_ambient_cheap_route_is_blocked(monkeypatch):
    # the self-grading case: a Qwen/GLM session's ambient route
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    with pytest.raises(C.RouteError, match="trust_ambient_route"):
        C.require_judge_route()


def test_ambient_trust_opt_in_allows_route(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    write_config(tmp_path, monkeypatch, {"trust_ambient_route": True})
    base, _, source = C.require_judge_route()
    assert (base, source)[1] == "ambient"


def test_ambient_non_anthropic_public_host_blocked(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://my-litellm.example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    with pytest.raises(C.RouteError, match="not an Anthropic host"):
        C.require_judge_route()


def test_ambient_anthropic_hosts_allowed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    assert C.require_judge_route()[2] == "ambient"


def test_blocklist_still_blocks_known_dogfood_routes(monkeypatch):
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "http://127.0.0.1:8181")
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "k")
    with pytest.raises(C.RouteError, match="GLM"):
        C.require_judge_route()


def test_explicit_localhost_not_blocked_by_ambient_rule(monkeypatch):
    # legit dogfood tunnels live on localhost via SIDEEYE_JUDGE_* — explicit
    # layers are the user's informed choice (blocklist still applies)
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "k")
    assert C.require_judge_route()[2] == "env"


# --- `sideeye route` output ---------------------------------------------------

def test_describe_route_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("SIDEEYE_JUDGE_BASE_URL", "https://route.example")
    monkeypatch.setenv("SIDEEYE_JUDGE_API_KEY", "sk-super-secret-value")
    text, ok = C.describe_route()
    assert ok and "sk-super-secret-value" not in text
    assert "https://route.example" in text and "from env" in text
    assert "OK" in text


def test_describe_route_unconfigured_shows_help(monkeypatch):
    text, ok = C.describe_route()
    assert not ok and "no judge route" in text and "SIDEEYE_CONFIG" not in text
    assert "SIDEEYE_JUDGE_BASE_URL" in text  # actionable, not just "error"


def test_describe_route_blocked_ambient(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://10.0.0.5:8000")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    text, ok = C.describe_route()
    assert not ok and "BLOCKED" in text and "self" not in text  # message about cheap route
    assert "trust_ambient_route" in text
