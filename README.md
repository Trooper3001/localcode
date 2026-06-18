# localcode

A terminal coding agent tailored to **Qwen3.6-27B**, built to run against
OpenRouter today and switch to **local quantized (GGUF) inference** later with no
behavioral change. Designed for **minimal token usage** and **long agentic
loops**. See [`SPEC.md`](SPEC.md) for the full design.

> A full-screen Cthulhu-themed TUI, adaptive reasoning for token economy, a
> content-block tool protocol, persistent memory + resumable sessions, clipboard
> image paste (vision), and a tsundere personality. Pure standard library — no
> runtime dependencies.

## Install

Needs Python 3.10+. Zero runtime dependencies (stdlib only).

```bash
git clone https://github.com/jannis/localcode && cd localcode
./install.sh            # installs the `localcode` command + runs first-time setup
```

`install.sh` uses `pipx` if available, else `pip --user`. Manual alternative:

```bash
pip install -e .        # then:  localcode setup
```

Or run without installing, straight from the repo:

```bash
python3 -m localcode
```

### Windows

localcode runs on Windows, but it drives **bash** (the model is trained on it),
so install **[Git for Windows](https://git-scm.com/download/win)** (gives Git
Bash) or use **WSL**. localcode auto-detects `bash` on PATH, then Git Bash, then
`$LOCALCODE_BASH` if you set it. Notes:

- The full-screen TUI needs `windows-curses` (installed automatically via
  `pip install`). If it's missing, localcode falls back to the plain REPL
  (`--plain`) automatically.
- It detects `python`/`python3` automatically for running code and tests.
- Clipboard screenshot paste uses PowerShell.
- Best experience: **Windows Terminal** (truecolor) + a Nerd Font, or just run
  everything inside **WSL** for a native-Linux experience.

## First-time setup

```bash
localcode setup
```

An interactive wizard: pick your backend (OpenRouter or local KoboldCPP), paste
your OpenRouter API key (saved to `~/.localcode/.env`, chmod 600 — never in
source), choose your model, tell it your name, and toggle the personality. Re-run
any time to change settings. Settings live in `~/.localcode/config.toml`
(global) and can be overridden per-project in `./.localcode/config.toml`.

Get an OpenRouter key at https://openrouter.ai/keys.

## Run

```bash
localcode                 # full-screen TUI (OpenCode-style, Cthulhu-themed)
localcode "fix calc.py"   # one-shot, prints to stdout
localcode --plain         # simple line REPL instead of the TUI
```

### The TUI

Launching with no task opens a full-screen terminal app: the Cthulhu idol
banner, a scrolling transcript (your prompts, the live tool log, inline diffs,
answers), an input line, and a status footer with an animated summoning spinner.

| Key | Action |
|---|---|
| `Enter` | send the typed task |
| `Ctrl-V` | paste a screenshot from the clipboard (vision) |
| `Esc` | cancel the current run — aborts the in-flight request immediately |
| `PgUp` / `PgDn` / `↑` / `↓` | scroll the transcript |
| `Ctrl-U` | clear the input line |
| `Ctrl-Q` | quit |

In-TUI commands:

| Command | Effect |
|---|---|
| `/yolo` | toggle auto-approve (apply edits / run without asking) |
| `/readonly` | toggle hard read-only (no writes or commands) |
| `/steps N` · `/steps off` | set the step budget, or ignore it entirely |
| `/think` | toggle model reasoning |
| `/web` | toggle web-search tools |
| `/verbose` | cycle quiet → normal → verbose |
| `/undo` · `/resume` · `/clear` · `/help` · `/quit` | as named |

When an edit/command needs approval (default mode), a `[y/n]` prompt appears on
the input line.

### Pasting screenshots (vision)

Copy an image to the clipboard, press `Ctrl-V` in the TUI (you'll see
`📎 screenshot attached`), type your question, and `Enter`. The image is sent to
Qwen3.6's vision path. Needs `wl-paste` (Wayland), `xclip` (X11), or
`pngpaste`/`osascript` (macOS). Images are only sent to the OpenRouter backend;
local GGUF is text-only unless an mmproj/vision model is loaded.

> Best in a **truecolor terminal** with a font that has box-drawing + braille
> glyphs (e.g. JetBrains Mono, a Nerd Font). Falls back to the plain REPL if
> curses can't start.

## The model decides

You don't set a mode. Say what you want; the model picks how to respond — answer
in words, read the repo and explain, run a command, or edit-and-verify code.

```bash
python3 -m localcode "how does auth work in this project?"   # reads + explains
python3 -m localcode "what's using port 8080?"               # runs a command
python3 -m localcode "add a /health endpoint and test it"    # edits + verifies
```

## Permissions (the one thing you control)

Reading is always free. Writing/running is **approval-gated by default**.

| Flag | Effect |
|---|---|
| *(default)* | Asks before each edit/command (when run in a TTY). |
| `--yolo` | Apply + run without asking (unattended/long runs). |
| `--read-only` | Hard-refuse every write/exec, no matter what the model decides. |
| `--dry-run` | Show what it would do; change nothing. |

## Other flags

```
--backend openrouter|koboldcpp   # default openrouter
--model NAME                     # default qwen/qwen3.6-27b
-C, --workspace DIR              # project dir (default: cwd)
--max-steps N                    # agentic step budget (default 24)
--web                            # enable web_search/web_fetch (off by default)
--no-think                       # disable model reasoning (faster)
--review                         # self-review the run's diff when done
--verbose | --quiet              # transparency level
```

## Interactive commands

`/undo` `/resume` `/review` `/readonly` `/verbose` `/help` `/quit` — anything
else is sent to the model.

## Sessions & memory

Every run is **autosaved** to `.localcode/sessions/`. Resume later:

```bash
python3 -m localcode --continue            # resume the most recent session
python3 -m localcode --resume 20260618-1530   # resume a specific id
python3 -m localcode --sessions            # list saved sessions
```
In the TUI: `/sessions` to list, `/load ID` to resume, or start with `--continue`.

**Project memory** lives in `.localcode/memory.md`. The agent calls `remember(fact)`
to persist durable facts ("tests run with `pytest -q`", "db is in `db/`"), and
they're loaded into context at the start of every session so it doesn't
re-discover the project each time. Edit `memory.md` by hand too.

## Personality

localcode has a **tsundere, dry, sarcastic** voice that's always genuinely
helpful and proactively suggests things (the bug you didn't ask about, a missing
test, the next step). It only colours prose — never tool calls or code. Turn it
off with `--no-persona` or `persona = false` in config.

## Configuration & secrets

Secrets are **never** stored in source. The OpenRouter key is read from, in
order: `OPENROUTER_API_KEY` env var → `.env` in the workspace → (temporary
fallback) a `sk-or-v1-…` key found in `test.py`.

```bash
cp .env.example .env   # then put your key in it
# or: export OPENROUTER_API_KEY=sk-or-v1-...
```

> ⚠️ `test.py` currently contains a hardcoded key. Rotate it on OpenRouter and
> delete `test.py` once you've set the env var / `.env`.

## Local inference (later)

Run Qwen3.6 GGUF under KoboldCPP on port 5001, then:

```bash
python3 -m localcode --backend koboldcpp "fix the failing test"
```

Same loop, same tools, same behavior — only the transport changes.

## Layout

```
localcode/
  config.py    config + secret loading (env / .env / config.toml)
  backend.py   LLMBackend: OpenRouter (streaming) + KoboldCPP, mid-request abort
  prompt.py    Qwen3.6 chat-ml render + tool-protocol + persona/memory/profile
  parser.py    lenient <tool> + <text> content-block extraction
  tools.py     registry + fs/edit/exec/docker/web/remember tools (permissions)
  loop.py      agent loop: gating, test-gate, trimming, cancel, review, undo
  store.py     persistent memory + resumable sessions
  profile.py   auto-detected project PROFILE
  art.py       Cthulhu banner + spinner + deep-purple palette
  tui.py       full-screen curses TUI (transcript, commands, image paste)
  setup.py     `localcode setup` first-run wizard
  clipboard.py screenshot paste for vision
  cli.py       one-shot + interactive (TUI / plain REPL)
```

## Status (see SPEC §12 milestones)

Done & tested against `qwen/qwen3.6-27b`:

- **M2 — verification loop**: enforced **test-gate** (won't accept "done" while
  the project's tests fail), **stuck detection**, real mid-request **cancel**,
  syntax gate, empty/truncated-reply recovery. *(Uses adaptive ReAct rather than
  a rigid staged PLAN→ACT→VERIFY→DEBUG pipeline — the gate gives the same
  guarantee.)*
- **M3 — context economy**: adaptive reasoning, **summarize-and-evict** trimming
  with an emergency aggressive-compaction fallback, content-block tool protocol,
  live token/step footer.
- **M4 — project learning**: `memory.md` + `remember` tool, resumable sessions
  (`--continue`/`--resume`), auto-generated `PROFILE.md`.

Remaining:

- **M6**: validated parity + latency/token benchmarks on a local GGUF
  (KoboldCPP backend is implemented but unverified — needs the model running).
- A true staged pipeline is optional; the ReAct loop + test-gate already meets
  the verification goal.
