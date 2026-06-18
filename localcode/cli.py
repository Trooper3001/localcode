"""localcode CLI — one-shot and interactive REPL (SPEC §4A run forms)."""
from __future__ import annotations

import sys
import argparse

from .config import Config
from .backend import make_backend, BackendError
from .loop import Session
from . import art


BANNER = "localcode — Qwen3.6 terminal agent"

HELP = """\
commands:
  /undo        revert this/last run's file changes
  /resume      continue the last run
  /review      self-review the last run's diff (read-only)
  /readonly    toggle read-only for this session
  /verbose     cycle quiet → normal → verbose
  /help        this
  /quit        exit
anything else is sent to the model, which decides how to respond.
"""


def build_parser():
    p = argparse.ArgumentParser(prog="localcode", description=BANNER)
    p.add_argument("task", nargs="*", help="what you want; omit for interactive mode")
    p.add_argument("--backend", choices=["openrouter", "koboldcpp"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", dest="base_url", default=None)
    p.add_argument("-C", "--workspace", default=None, help="project dir (default: cwd)")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--read-only", action="store_true", help="hard-forbid any write/exec")
    p.add_argument("--yolo", action="store_true", help="apply/run without asking")
    p.add_argument("--dry-run", action="store_true", help="preview writes/commands only")
    p.add_argument("--web", action="store_true", help="enable web_search/web_fetch")
    p.add_argument("--no-think", action="store_true", help="disable model reasoning")
    p.add_argument("--review", action="store_true", help="self-review the diff when done")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--plain", action="store_true",
                   help="use the simple line REPL instead of the full-screen TUI")
    p.add_argument("--continue", dest="cont", action="store_true",
                   help="resume the most recent session in this workspace")
    p.add_argument("--resume", metavar="ID", help="resume a specific session id")
    p.add_argument("--sessions", action="store_true", help="list saved sessions and exit")
    p.add_argument("--no-persona", action="store_true", help="disable the tsundere voice")
    return p


def cfg_from_args(a) -> Config:
    verbosity = "verbose" if a.verbose else "quiet" if a.quiet else None
    return Config.load(
        backend=a.backend, model=a.model, base_url=a.base_url, workspace=a.workspace,
        max_steps=a.max_steps,
        read_only=a.read_only or None,
        allow_writes=True if a.yolo else None,
        dry_run=True if a.dry_run else None,
        web_enabled=True if a.web else None,
        review=True if a.review else None,
        think=False if a.no_think else None,
        persona=False if a.no_persona else None,
        verbosity=verbosity,
    )


def _resume_into(sess, store, args):
    """Apply --continue/--resume to a session. Returns a status string or None."""
    data = None
    if args.resume:
        data = store.load_session(args.resume)
        if not data:
            return f"no session '{args.resume}'"
    elif args.cont:
        data = store.latest_session()
        if not data:
            return "no previous session in this workspace"
    if data:
        n = sess.resume(data)
        return f"resumed session {data.get('id')} ({n} messages)"
    return None


def interactive(sess: Session):
    ui = sess.ui
    print(art.banner(
        f"backend={sess.cfg.backend} · model={sess.cfg.model} · {sess.cfg.workspace}"))
    print("\n   " + art.dim("/help for the rites · /quit to banish") + "\n")
    while True:
        try:
            line = input(art.c(art.ACCENT, "ᛝ ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            return
        if line == "/help":
            print(HELP); continue
        if line == "/undo":
            print(sess.undo()); continue
        if line == "/resume":
            sess.run("continue."); continue
        if line == "/review":
            sess._review(); continue
        if line == "/readonly":
            sess.cfg.read_only = not sess.cfg.read_only
            sess.messages[0]["content"] = sess._system()
            print(ui._c(f"read-only = {sess.cfg.read_only}", "\033[33m")); continue
        if line == "/verbose":
            order = ["quiet", "normal", "verbose"]
            sess.cfg.verbosity = order[(order.index(sess.cfg.verbosity) + 1) % 3]
            ui.verbosity = sess.cfg.verbosity
            print(ui._c(f"verbosity = {sess.cfg.verbosity}", "\033[33m")); continue
        if line.startswith("/"):
            print(ui._c(f"unknown command {line}", "\033[31m")); continue
        try:
            sess.run(line)
        except KeyboardInterrupt:
            print("\nbye"); return


def main(argv=None):
    # `localcode setup` / `config` / `init` → first-run wizard (before arg parsing
    # so it works with zero config and no API key present)
    import sys as _sys
    raw = argv if argv is not None else _sys.argv[1:]
    if raw and raw[0] in ("setup", "config", "init"):
        from .setup import run_setup
        return run_setup()

    args = build_parser().parse_args(argv)
    try:
        cfg = cfg_from_args(args)
        backend = make_backend(cfg)
    except (BackendError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    from .store import Store
    store = Store(cfg.workspace)

    if args.sessions:
        rows = store.list_sessions()
        if not rows:
            print("no saved sessions in this workspace.")
        for r in rows:
            import datetime
            when = datetime.datetime.fromtimestamp(r["updated"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {r['id']}  {when}  {r['title']}")
        return 0

    task = " ".join(args.task).strip()
    if task:
        sess = Session(cfg, backend)
        status = _resume_into(sess, store, args)
        if status:
            print(art.dim(status))
        sess.run(task)
        return 0

    # interactive: full-screen TUI by default, plain REPL on request / fallback
    if not args.plain and sys.stdout.isatty():
        try:
            from . import tui
            tui.launch(cfg, backend, resume=(args.resume or ("latest" if args.cont else None)))
            return 0
        except Exception as e:
            print(f"(TUI unavailable: {e} — falling back to plain REPL)\n",
                  file=sys.stderr)
    sess = Session(cfg, backend)
    status = _resume_into(sess, store, args)
    if status:
        print(status)
    interactive(sess)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
