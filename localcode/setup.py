"""First-time setup wizard: `localcode setup`.

Writes ~/.localcode/config.toml (settings) and ~/.localcode/.env (the API key,
chmod 600). Re-runnable any time to change settings. Stdlib only.
"""
from __future__ import annotations

import os
import getpass

from . import art, config


def _ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(art.c(art.ACCENT, f"  {prompt}{suffix}: ")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return ans or default


def _ask_yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    ans = _ask(f"{prompt} ({d})").lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def run_setup() -> int:
    print(art.banner())
    print("\n  " + art.c(art.RUNE, "first-time setup") +
          art.dim("  — press Enter to accept defaults\n"))

    cfg_dir = config.GLOBAL_DIR
    cfg_dir.mkdir(parents=True, exist_ok=True)

    backend = _ask("backend (openrouter / koboldcpp)", "openrouter").lower()
    settings = {"backend": backend}
    api_key = None

    if backend == "koboldcpp":
        settings["base_url"] = _ask("KoboldCPP url", config.KOBOLDCPP_URL)
        settings["model"] = _ask("model name (optional)", "")
    else:
        backend = "openrouter"
        settings["backend"] = "openrouter"
        settings["model"] = _ask("model", config.DEFAULT_MODEL)
        existing = os.environ.get("OPENROUTER_API_KEY", "")
        if existing and _ask_yesno("use the OPENROUTER_API_KEY already in your env?", True):
            api_key = None  # leave it to the env
        else:
            print(art.dim("  get a key at https://openrouter.ai/keys"))
            try:
                api_key = getpass.getpass(art.c(art.ACCENT, "  paste OpenRouter API key (hidden): ")).strip()
            except (EOFError, KeyboardInterrupt):
                api_key = ""

    name = _ask("what should I call you? (optional)", "")
    if name:
        settings["user_name"] = name
    persona = _ask_yesno("enable the tsundere/sarcastic personality?", True)
    settings["persona"] = persona
    if _ask_yesno("auto-approve edits & commands by default (yolo)?", False):
        settings["allow_writes"] = True

    # write config.toml
    cfg_path = cfg_dir / "config.toml"
    lines = ["# localcode global config — edit freely, or re-run `localcode setup`\n"]
    for k, v in settings.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}\n")
        else:
            lines.append(f'{k} = "{_toml_escape(str(v))}"\n')
    cfg_path.write_text("".join(lines))

    # write the key to ~/.localcode/.env (chmod 600), never into config.toml
    if api_key:
        env_path = cfg_dir / ".env"
        env_path.write_text(f"OPENROUTER_API_KEY={api_key}\n")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass

    print()
    print(art.c(art.GOOD, "  ✓ saved to ") + art.dim(str(cfg_path)))
    if api_key:
        print(art.c(art.GOOD, "  ✓ key saved to ") + art.dim(str(cfg_dir / '.env') + " (chmod 600)"))
    hi = f", {name}" if name else ""
    print("\n  " + art.c(art.RUNE, f"all set{hi}. start me with:") + art.c(art.ACCENT, "  localcode"))
    if persona:
        print("  " + art.dim("...don't expect me to be nice about it."))
    print()
    return 0
