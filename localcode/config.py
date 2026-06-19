"""Configuration + secret loading.

Precedence: explicit args > env vars > .env > config.toml > defaults.
Config files: ./.localcode/config.toml (project) over ~/.localcode/config.toml
(global). Secrets are NEVER stored in source: the OpenRouter key comes from the
OPENROUTER_API_KEY env var, a .env file, or ~/.localcode/.env (written by the
`localcode setup` wizard). A sibling test.py is a temporary last-resort.
"""
from __future__ import annotations

import os
import re
import pathlib
from dataclasses import dataclass, field

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover - py3.10
    tomllib = None


DEFAULT_MODEL = "qwen/qwen3.6-27b"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
KOBOLDCPP_URL = "http://127.0.0.1:5001"

GLOBAL_DIR = pathlib.Path.home() / ".localcode"


def _load_dotenv(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        # fill missing OR empty env vars (an empty export shouldn't shadow .env)
        if not os.environ.get(k):
            os.environ[k] = v.strip().strip('"').strip("'")


def _load_toml(path: pathlib.Path) -> dict:
    if tomllib is None or not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _scrape_legacy_key(root: pathlib.Path) -> str:
    """Last-resort: pull the key out of test.py so testing works today.
    A deliberate, temporary convenience. Rotate + delete test.py."""
    f = root / "test.py"
    if not f.exists():
        return ""
    m = re.search(r"(sk-or-v1-[A-Za-z0-9]+)", f.read_text(errors="ignore"))
    return m.group(1) if m else ""


@dataclass
class Config:
    backend: str = "openrouter"          # openrouter | koboldcpp
    model: str = DEFAULT_MODEL
    base_url: str = ""                    # filled per-backend if empty
    api_key: str = ""
    workspace: pathlib.Path = field(default_factory=lambda: pathlib.Path.cwd())
    user_name: str = ""                   # for a personalized greeting/voice
    max_steps: int = 40            # ceiling, not a target — the loop stops as soon
    #                                as the model finishes; raised so non-trivial
    #                                builds complete in one prompt instead of
    #                                forcing the user to type "continue".
    ctx_len: int = 32768
    temperature: float = 0.3
    think: bool = True                    # Qwen3.6 reasoning toggle
    allow_writes: bool = False            # True = --yolo: apply/run without asking
    dry_run: bool = False                 # show edits/commands, change nothing
    read_only: bool = False               # hard-refuse every write/exec tool
    web_enabled: bool = False             # web_search/web_fetch off unless asked
    docker_enabled: bool = True
    review: bool = False                  # self-review the run's diff when done
    verbosity: str = "normal"             # quiet | normal | verbose
    persona: bool = True                  # tsundere/sarcastic helpful voice
    test_gate: bool = True                # block "done" while project tests fail

    @classmethod
    def load(cls, **overrides) -> "Config":
        root = pathlib.Path(overrides.get("workspace") or pathlib.Path.cwd()).resolve()
        # .env files (global first so project can override)
        _load_dotenv(GLOBAL_DIR / ".env")
        _load_dotenv(root / ".env")
        # config.toml: project overrides global; both are base defaults
        toml = {**_load_toml(GLOBAL_DIR / "config.toml"),
                **_load_toml(root / ".localcode" / "config.toml")}

        def pick(key, env=None, default=None):
            """overrides > env var > toml > default."""
            if overrides.get(key) is not None:
                return overrides[key]
            if env and os.environ.get(env):
                return os.environ[env]
            if key in toml:
                return toml[key]
            return default

        c = cls()
        c.workspace = root
        c.backend = pick("backend", "LOCALCODE_BACKEND", c.backend)
        c.model = pick("model", "LOCALCODE_MODEL", c.model)
        c.user_name = pick("user_name", default=c.user_name) or ""

        if c.backend == "openrouter":
            c.base_url = pick("base_url", "OPENROUTER_URL", OPENROUTER_URL)
            c.api_key = (os.environ.get("OPENROUTER_API_KEY", "")
                         or toml.get("api_key", "")
                         or _scrape_legacy_key(root))
        elif c.backend == "koboldcpp":
            c.base_url = pick("base_url", "KOBOLDCPP_URL", KOBOLDCPP_URL)
        else:
            raise ValueError(f"unknown backend: {c.backend}")

        for k in ("max_steps", "temperature", "ctx_len"):
            v = pick(k)
            if v is not None:
                setattr(c, k, v)
        for flag in ("think", "allow_writes", "dry_run", "read_only",
                     "web_enabled", "docker_enabled", "review", "persona",
                     "test_gate"):
            v = pick(flag)
            if v is not None:
                setattr(c, flag, v)
        c.verbosity = pick("verbosity", default=c.verbosity)
        return c
