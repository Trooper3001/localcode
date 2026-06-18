# localcode — Specification

> A terminal coding agent tailored to **Qwen3.6-27B**, designed to run against
> OpenRouter today and switch to **local quantized (GGUF) inference** tomorrow
> with no behavioral change. Built for **minimal token usage** and **long,
> uninterrupted agentic loops**.

Status: draft v0.1 · Owner: jannis · Target model: `qwen/qwen3.6-27b`

---

## 1. What localcode is

localcode is a single-binary-feel terminal agent (CLI + optional TUI) in the
spirit of ClaudeCode / OpenCode / QwenCode, but **specialized for one mid-size
model running locally**. Everything in the design exists to compensate for the
two constraints of a 27B GGUF model on consumer hardware:

1. **Tokens are expensive** — context window is finite and every token costs
   latency on local inference. The agent must say and read as little as
   possible while still being effective.
2. **The model is good but not frontier** — it needs a tight, staged loop,
   surgical tools, and hard verification gates so it can run long without
   drifting or declaring false success.

It must let the user, from the terminal:

- make **quick, surgical code edits** to an existing project,
- **scaffold new projects** and run/test them,
- **find and fix bugs** with self-verification,
- **interact with the host system** — run commands, manage Docker containers,
  wire up dev environments,
- **just talk to the model** or **ask read-only questions about the project**
  without it changing anything — the model decides how to respond to each
  request; it doesn't need to be told (see §4A).

### Non-goals (v1)
- No web IDE / Monaco frontend (CLI/TUI only; a server mode is a later option).
- No multi-user / cloud-hosted service.
- No fine-tuning of the model. We engineer *around* the model, not on it.
- Not model-agnostic by design — Qwen3.6 is the first-class target. Other models
  may work but are not tuned for.

---

## 2. Design principles

| Principle | Consequence in the design |
|---|---|
| **Token economy first** | Repo map over file dumps; line-ranged reads; diffs not full files; terse system prompt; summarize-and-evict old turns. |
| **Local parity** | Identical behavior on OpenRouter and KoboldCPP. The tool protocol must not depend on a provider-specific feature. |
| **Surgical over wholesale** | Editing tools operate on lines/functions/symbols, never "rewrite the file" unless creating it. |
| **Verify, don't trust** | The loop cannot terminate as "done" until syntax-check + tests pass. The model's self-assessment is never sufficient. |
| **Learn the project once** | Persist a project profile + memory so the agent doesn't re-discover the codebase every session. |
| **Fail soft, recover in-loop** | Errors (bad tool args, broken syntax, failed test) are fed back as compact observations, not crashes. |

---

## 3. Inference backend abstraction

A single `LLMBackend` interface decouples the agent from the provider. All
backends speak a **raw text completion** contract (prompt in → tokens out,
streaming), because that is the lowest common denominator and the cheapest path
(see §5).

```
LLMBackend
  .complete(prompt, *, stop, max_tokens, temperature, stream) -> token stream
  .health() -> ok | offline
  .capabilities -> { native_tools: bool, fim: bool, ctx_len: int }
```

### Backends

| Backend | Endpoint | Use | Notes |
|---|---|---|---|
| **OpenRouter** (dev default) | `POST /api/v1/chat/completions` (or `/completions`) | Today | `model="qwen/qwen3.6-27b"`, `extra_body={"reasoning":{"enabled": <think>}}`. Key from env, never hardcoded. |
| **KoboldCPP** (local target) | `POST /api/v1/generate` or `/v1/completions` | Primary local | GGUF Q4/Q5/Q8. Supports `genkey` abort + streaming. Matches bonsai's proven path. |
| **llama.cpp server** | `/completion` | Alt local | Same raw-completion contract. |
| **Ollama** (optional) | `/api/generate` | Convenience local | Easiest setup; less sampling control. |

Backend is selected by config / `--backend` flag. The **prompt rendering**
(Qwen3.6 chat template + the tool-protocol block) is identical across all of
them; only the transport differs.

### Qwen3.6 specifics
- Render with Qwen3 chat template (`<|im_start|>role … <|im_end|>`).
- **Thinking toggle**: Qwen3.6 is a reasoning model. Reasoning is *on* for
  Plan/Debug phases, *off* for routine tool steps to save tokens. Strip
  `<think>…</think>` from anything stored back into context.
- Stop sequences scoped per phase so generation halts at the first complete
  tool call (don't let it hallucinate the observation).

---

## 4. Architecture

```
localcode/
  cli.py            Entry point: arg parsing, REPL/one-shot, TUI launch
  config.py         Config + secrets loading (env > .localcode/config.toml > defaults)
  backend/
    base.py         LLMBackend interface
    openrouter.py
    koboldcpp.py
    llamacpp.py
    ollama.py
  engine/
    loop.py         The agentic loop (phases, step budget, termination gates)
    prompt.py       Qwen3.6 template render + tool-protocol block render
    parser.py       Tool-call extraction from raw model output (lenient JSON)
    context.py      Token-budget manager: repo map, eviction, summarization
    verify.py       Syntax check + test runner gates
  tools/
    registry.py     Tool schema + dispatch (one place defines a tool)
    fs.py           read_file, list_dir, search, write_file, edit tools
    edit.py         replace_lines, replace_range, replace_function, rename_symbol, append_file
    exec.py         run_command, run_file (sandbox-aware, timeouts)
    docker.py       docker_* helpers (ps, build, run, logs, compose)
    web.py          web_search, web_fetch (optional, off by default)
  project/
    profile.py      Project learning: build & persist LOCALCODE.md + repo map
    memory.py       Persistent facts/decisions across sessions
  tui/              Optional Textual-based TUI (panes: transcript, diff, tool log)
```

The **CLI** is the product; the **engine** is a library that a future server/IDE
could reuse.

---

## 4A. Behavior — the model decides

There are **no user-set modes**. You never declare "chat" vs "agent". You just
say what you want and the model decides how to respond — answer in words,
read the repo to explain something, run a system command, or edit code and
verify it. The same way you'd talk to a competent teammate: you don't tell them
"enter editing mode," you state the goal.

The model always has the full toolset available and chooses what (if anything)
to use. Intent it routes itself:

| If you say… | The model tends to… | Touches disk? |
|---|---|---|
| "what's the difference between X and Y?" | just answer | no |
| "how does auth work in this project?" | read/search the repo, then explain | reads only |
| "what's using port 8080?" / "list my containers" | run a shell/Docker command, report back | runs, no edits |
| "fix the failing test in auth.py" | edit → run → fix → verify loop (§7) | yes |
| "build me a FastAPI todo app" | scaffold, install, run, test | yes |

This means the *response* is emergent from the request, not from a flag. A
question gets an answer; a task gets work. If the model is unsure whether you
want it to actually change things, it asks first rather than guessing.

### The only hard boundary: writes & commands are gated, not the model's choice

What the model is *allowed* to do (read is always free; **write/execute is
gated**) is enforced by the runtime, independent of what the model decides:

- Default **ask-before-act**: when the model wants to edit a file or run a
  command, the runtime shows the diff / the command and waits for your OK.
  The model proposes; you approve. (This is the safety net for "it decided to
  change stuff I didn't want.")
- `--yolo` / `allow_writes=true`: trust it, apply + run without prompting —
  for unattended/long agentic runs.
- `--read-only`: a hard override. The runtime refuses every write/exec tool no
  matter what the model decides, so you can talk and ask freely with a
  structural guarantee that nothing changes. (The one case where *you* constrain
  it, because "guaranteed no changes" is a promise the model alone can't make.)
- `--dry-run`: model acts as normal but the runtime turns every write/exec into
  a preview.

So: **the model picks the behavior; the runtime governs the permissions.** Read
is always allowed; mutating the world is approval-gated by default and can be
hard-disabled by you when you want a pure read-only session.

### Run forms
- **One-shot**: `localcode "how does routing work?"` — responds, exits.
- **Interactive REPL/TUI**: persistent session; the model shifts between
  answering, reading, running, and editing turn to turn as the conversation
  moves; live tool log; approve-edits view.

---

## 5. Tool-calling protocol (token-minimal, local-parity)

**Decision: hand-crafted tool calls over raw completions, with a native-tools
adapter as opt-in.**

Rationale: native `tools=` / structured `tool_calls` (a) costs more tokens
(JSON schema echoed every turn, verbose call/result envelopes), and (b) on
local llama.cpp/KoboldCPP forces grammar-constrained sampling that is markedly
slower. A compact text protocol is provider-independent and gives identical
behavior on OpenRouter and GGUF.

### Wire format
The model emits exactly one tool call per step as a fenced block:

```
<tool>
{"name":"replace_lines","path":"auth.py","start":42,"end":47,"text":"..."}
</tool>
```

- Generation **stops** at `</tool>` (stop sequence). The runtime executes the
  tool and appends a compact observation:

```
<obs>ok: replaced 6 lines (42-47). syntax: clean</obs>
```

- The parser is **lenient**: tolerates missing trailing braces, single quotes,
  and trailing prose; if it can't parse, it returns a one-line error obs asking
  for a corrected call (no crash, no wasted full turn).
- The `registry` defines each tool **once** (name, args, one-line description,
  whether it mutates). The prompt renders a *minimal* signature list, not full
  JSON schema, to save tokens.

### Adapter
`ToolProtocol` has two implementations behind one interface: `RawText` (default)
and `NativeFunctions` (uses backend `tools=` when `capabilities.native_tools`).
Tool definitions and dispatch are shared; only render+parse differ.

### Tool catalog (v1)

| Tool | Mutates | Purpose |
|---|---|---|
| `list_dir(path, depth?)` | no | Shallow dir listing (respects ignore rules). |
| `read_file(path, start?, end?)` | no | **Line-ranged** read — default returns a window, not the whole file. |
| `search(query, glob?)` | no | ripgrep-style code search; returns `path:line: match`. |
| `write_file(path, text)` | yes | Create / overwrite (used for new files only). |
| `replace_lines(path, start, end, text)` | yes | Surgical line replacement. |
| `replace_function(path, name, text)` | yes | Replace a whole function/method/class body by name. |
| `rename_symbol(old, new, scope?)` | yes | Project-wide rename. |
| `append_file(path, text)` | yes | Append (configs, tests). |
| `run_command(cmd, timeout?)` | yes | Shell command (bash). Captures stdout/stderr/exit. |
| `run_file(path)` | yes | Detect language, run, return output (drives the test gate). |
| `docker_*` | yes | `docker_ps`, `docker_build`, `docker_run`, `docker_logs`, `docker_compose` — manage containers/dev envs. |
| `web_search` / `web_fetch` | no | Optional, opt-in; look up docs the model lacks. |

After every mutating file tool, the runtime auto-runs a **language syntax
check** and folds the exact broken line into the observation so the next step is
a one-call fix.

---

## 6. Context & token management (the core differentiator)

The agent must "work as long as possible." That is a **context-budget** problem.

### Repo map instead of file dumps
On first contact with a project, `project/profile.py` builds a compact **repo
map**: directory skeleton + per-file symbol outline (functions/classes/exports),
bounded to a token budget (e.g. ≤ ~1.5k tokens). The model navigates via
`search` + ranged `read_file` rather than ingesting whole files. This is the
single biggest token saver.

### Budgeted, self-pruning context
`engine/context.py` owns a token budget (e.g. 70% of `ctx_len`). Each turn it:
1. Always keeps: system prompt, tool block, repo map, current task, last N
   observations.
2. **Summarizes-and-evicts** older tool steps into a one-line digest
   ("read auth.py:1-40; found login() bug at L42") when over budget.
3. Drops verbose tool outputs after they've been acted on (keeps the conclusion,
   not the raw dump).

### Cheap by construction
- System prompt is terse and static (cache-friendly).
- Observations are one line where possible.
- Reads are ranged; edits return diffs/line counts, not echoed file contents.
- Reasoning (`<think>`) is enabled only for phases that need it and never stored.

### Target
A typical "fix a bug" task should fit in **< 8k tokens of live context** at any
moment regardless of repo size, and run 15–30 tool steps without a context
reset.

---

## 7. The agentic loop

A staged loop keeps a mid-size model on track and recovers from errors in place.

```
PLAN  → (think on)  produce a short ordered step list (no code yet)
  └─ for each step:
       ACT   → (think off) emit one tool call
       OBSERVE → execute, fold result (incl. syntax check) back in
       (repeat ACT/OBSERVE until step satisfied)
VERIFY → run tests / run_file; must pass
  ├─ pass → DONE (print summary + unified diff)
  └─ fail → DEBUG (think on) → back to ACT with the failure as the new sub-task
```

### Long-run mechanics
- **Step budget** (`--max-steps`, default e.g. 24) with auto-extension when
  measurable progress is detected (tests moving from N→N-1 failures).
- **Termination gates** — cannot emit "done" while: syntax errors exist, the
  declared test/run command fails, or required files are missing
  (`_auto_verify` equivalent). Borrowed directly from bonsai's proven gate.
- **Stuck detection** — if the same tool+args repeat or no file/test progress
  over K steps, the loop injects a terse "you are stuck; try a different
  approach / search the repo" nudge instead of looping forever.
- **Interrupt / cancel** — see §7A. Ctrl-C stops the run at any point without
  killing the session.

---

## 7A. Interrupting & cancelling

A long agentic loop is useless if you can't stop it. Cancellation is a
first-class capability, not a kill -9.

- **Ctrl-C — single press**: cancels the *current activity* and hands control
  back. What it means depends on where the loop is:
  - mid-generation → **aborts the in-flight model generation** at the transport
    level (KoboldCPP `genkey` abort / closing the OpenRouter stream) so no
    further tokens are paid for;
  - mid-tool (e.g. a long `run_command`/test) → **terminates the child process**
    (process-group kill, honoring the tool's timeout machinery);
  - between steps → **stops the loop** before the next step.
  In every case the **session survives** — partial work and transcript are kept,
  and you drop back to the prompt.
- **Ctrl-C — double press / `Ctrl-C` again within ~1s**: hard exit the whole
  program.
- **After an interrupt** you can: type a new instruction (which the model folds
  into the ongoing context — "actually, do X instead"), **`/resume`** to
  continue where it left off, or **`/undo`** to roll back the edits made so far
  this run (see below).
- **Esc** in the TUI = same as a single Ctrl-C (cancel current activity).
- **In-flight only, never corrupting**: a cancel never leaves a file
  half-written — edits are applied atomically per tool call, so an interrupt
  lands either fully before or fully after a given edit, never inside one.
- **Steering, not just stopping**: because cancel returns to the prompt with
  context intact, the primary use is *redirecting* a run that's going the wrong
  way ("stop — you're editing the wrong file"), which is cheaper than letting it
  finish and undoing.

`/undo` rolls back the file changes of the current (or last) run using a
per-run change journal; it does **not** revert side effects already executed in
the world (a container that was started, a package that was installed) — those
are reported so you can address them.

---

## 8. Project learning & memory

"Learn the project it's working in" = persisted, reused knowledge.

- **`./.localcode/PROFILE.md`** (auto-generated, refreshable): repo map, detected
  language/build/test commands, entry points, conventions. Loaded (compactly) at
  session start so the agent doesn't re-explore every time.
- **`./.localcode/memory/`**: durable facts & decisions the user or agent records
  ("tests run with `pytest -q`", "DB layer is in `db/`, don't touch migrations").
  One fact per file, loaded as a short index. Mirrors this harness's own memory
  model.
- **`LOCALCODE.md`** (user-authored, optional): project-specific instructions the
  user wants always in context (analogous to CLAUDE.md). Kept short on purpose.
- Profile/memory are **token-bounded** and summarized; learning the project must
  not blow the context budget it's meant to save.

---

## 9. Feature requirements (acceptance)

| Capability | Done when |
|---|---|
| Quick edit | `localcode "rename foo to bar in utils.py"` produces a correct surgical diff, syntax clean, no full-file rewrite. |
| New project | `localcode "create a FastAPI todo app with tests"` scaffolds files, installs deps, `run_file`/tests pass before "done". |
| Run & test | Agent detects and runs the project's test command; failures gate completion. |
| Bug fix | Given a failing test, agent localizes via search, edits surgically, re-runs until green. |
| System / Docker | Agent can build & run a container, read its logs, and report status via `docker_*` tools. |
| Local switch | Same task succeeds with `--backend koboldcpp` against a local GGUF, no code change. |
| Token economy | Live context stays within budget on a large repo (repo map + eviction verified). |
| Cancel / steer | Ctrl-C mid-generation stops token output immediately; mid-`run_command` kills the child; session stays alive and accepts a new instruction or `/resume` (SPEC §7A). |
| Transparency | Every tool call + key args + one-line result streams live; diffs always shown; status line tracks step/token budget (SPEC §11A). |
| Optional review | `--review` runs a read-only self-review of the run's diff and prints findings without editing (SPEC §11B). |

---

## 10. Configuration & secrets

- Precedence: **env vars > `./.localcode/config.toml` > `~/.localcode/config.toml`
  > defaults**.
- **Secrets never in source.** `OPENROUTER_API_KEY` read from env / `.env`.
  `.localcode/` and `.env` are git-ignored by default.
- ⚠️ **Immediate action item:** the key currently hardcoded in
  `localcode/test.py` must be rotated (it has been exposed) and replaced with an
  env lookup. `test.py` becomes a throwaway smoke test or is deleted.
- Key knobs: `backend`, `model`, `base_url`, `ctx_len`, `max_steps`,
  `think_phases`, `allow_writes`, `approve_edits`, `read_only`, `docker_enabled`,
  `web_enabled`, `review` (off/on), `verbosity` (quiet/normal/verbose).

---

## 11. Safety & UX

- **Write/exec confirmation**: default *ask* mode shows a diff / the command and
  requires approval; `--yolo` / `allow_writes=true` for unattended runs.
- **Sandbox awareness**: command timeouts, working-dir confinement
  (`safe_resolve`-style path jailing to the workspace root), output truncation.
- **Streaming + live tool log** so the user can watch and interrupt.
- Clear final output: summary + unified diff + test result.

### 11A. Transparency — see what it's doing

OpenCode-style visibility is a requirement, not a nice-to-have: you should
always be able to see what the model is thinking about and every tool it calls,
without drowning in raw output.

- **Live tool log**: every step prints as it happens — the tool name and its key
  arguments on one line, then a one-line result. Example:
  ```
  ▸ search "def login"                    3 hits
  ▸ read_file auth.py 30-60               ok
  ▸ replace_lines auth.py 42-42           ok · syntax clean
  ▸ run_command "pytest -q"               1 failed → 0 failed
  ```
- **Reasoning peek**: a short, dimmed line of what the model is *about to do* /
  why ("looking for where the token is validated…"). Off by default to save
  tokens/clutter; `--verbose` shows the full `<think>` stream, `--quiet` shows
  results only.
- **Detail on demand**: tool output is collapsed to a summary line; expand a
  step (TUI: select it; CLI: `--show-output` or `/last`) to see the full diff /
  command output. Keeps the scrollback readable on long runs.
- **Status line**: current step / step budget, live token count vs budget,
  elapsed time, backend + model — so you know how hard it's working and how much
  context is left.
- **Diffs, always**: any file change is shown as a unified diff inline, even in
  `--yolo`, so an unattended run still leaves a readable trail.

### 11B. Optional review

Reviewing the agent's work is opt-in — most quick edits don't need it, but for
anything non-trivial you can ask for a second look.

- **`--review` / `/review`**: after the run finishes (tests green), the model
  does a focused self-review pass over its own diff — looking for missed edge
  cases, leftover debug code, broken assumptions, things outside the asked
  scope — and prints findings. You then accept, ask it to address them, or
  `/undo`.
- **Review = read-only**: the review pass cannot edit; it only reports. Fixing
  findings is a separate, approved step (keeps "review" trustworthy and cheap).
- **Scope control**: by default reviews only the diff of the current run, not the
  whole repo, so it stays fast and token-light.
- Off by default; can be set to always-on per project in `.localcode/config`.

---

## 12. Milestones

1. **M0 — Backend + prompt** ✅: `LLMBackend` (OpenRouter + KoboldCPP), Qwen3.6
   render, streaming, thinking toggle, raw-completion smoke test.
2. **M1 — Tool loop** ✅: registry, raw-text protocol, parser, fs + edit + exec
   tools, syntax-check observation, single-task one-shot run.
3. **M2 — Verification loop** ✅: ReAct loop with syntax gate, **step budget**,
   **stuck detection**, **real abort/cancel** (mid-request), and an **enforced
   test-gate** (won't accept "done" while the project's tests fail when a run
   changed code — verified it catches an unmentioned bug). Empty-reply guard.
4. **M3 — Context economy** ✅: repo map, **adaptive reasoning** (think only on
   step 1 + after errors — ~3× faster), budgeted **summarize-and-evict**
   trimming, live token/step counter in the TUI footer.
5. **M4 — Project learning** ✅: **memory.md + `remember` tool** + auto-load,
   **resumable sessions** (`--continue`/`--resume`), and **auto-generated
   PROFILE.md** (language, test command, entry points, deps — detected once,
   loaded compactly so the agent doesn't re-explore each session).
6. **M5 — System/Docker tools** ✅ + interactive **full-screen TUI** (Cthulhu
   theme, slash commands, clipboard image paste, confirmation overlay) done.
7. **M6 — Local hardening** ☐: validate full parity on GGUF Q4/Q5, latency/token
   benchmarks vs OpenRouter.

### Protocol notes (implemented)
- **Content-block protocol**: file bodies go in a `<text>…</text>` block, never
  inside the JSON — eliminated the dominant failure mode (quotes/newlines
  breaking JSON). Parser also accepts `<tool_call>`, ```json fences, and a
  guarded function-paren dialect.
- **Adaptive reasoning**: reasoning is off for routine tool steps, on for
  planning/debugging — the single biggest token/latency win.

### Verified behaviour (stress tests, OpenRouter qwen3.6-27b)
- Create multi-file project (6 files, 439 lines, 25 tests): ~156s, 0 parse errors.
- Fix a bug in an existing codebase: ~12s, 3 steps.
- Add features to an existing codebase: ~18s, 5 tests pass.
- Memory persists and is recalled across `--continue`d sessions.

---

## 13. Open questions

- Default quantization for the 27B local target (Q4_K_M vs Q5)? Drives ctx_len
  and step budgets — settle during M6.
- TUI now (M5) or after a usable CLI ships? Spec assumes CLI-first.
- Web tools on by default or strictly opt-in for token/privacy reasons?
  (Spec defaults: off.)
