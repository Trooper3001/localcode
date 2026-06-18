"""The agent loop: model-decides behavior, permission gating, transparency,
cancel/steer, optional review (SPEC §4A, §7, §7A, §11).

This is the M1 ReAct loop. The staged PLAN→ACT→VERIFY→DEBUG pipeline (§7) and
budgeted context eviction (§6) are M2/M3 — noted with TODOs.
"""
from __future__ import annotations

import re
import sys
import json
import difflib
import pathlib
import threading

from . import prompt, parser, tools as toolmod, art, backend as backendmod, store as storemod


# --------------------------------------------------------------------------- #
# terminal output helpers (transparency, SPEC §11A)
# --------------------------------------------------------------------------- #

class UI:
    """Eldritch terminal output — deep-purple themed (see art.py palette)."""

    def __init__(self, verbosity="normal"):
        self.verbosity = verbosity

    # kept for callers that pass raw ANSI; routes through truecolor when sensible
    def _c(self, s, code=None):
        return f"{code}{s}\033[0m" if (code and sys.stdout.isatty()) else (
            s if code else s)

    def thought(self, text):
        if self.verbosity == "quiet":
            return
        line = text.strip().splitlines()[0][:100] if text.strip() else ""
        # skip trivial fragments (stray punctuation / 1-2 char leftovers)
        if len(re.sub(r"[^A-Za-z0-9]", "", line)) < 4:
            return
        print("  " + art.dim("≀ " + line))   # ≀ = a curling tendril of thought

    def tool(self, name, arg_summary, result_summary, ok=True):
        mark = art.c(art.GOOD if ok else art.ERR, "◆")
        head = art.c(art.ACCENT, name)
        res = art.c(art.GOOD if ok else art.ERR, result_summary)
        print(f"{mark} {head} {art.dim(arg_summary)}    {res}")

    def info(self, text):
        print(art.dim(text))

    def final(self, text):
        print("\n" + text.strip() + "\n")

    def diff(self, path, old, new):
        if self.verbosity == "quiet":
            return
        d = difflib.unified_diff(
            (old or "").splitlines(), (new or "").splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
        for line in d:
            if line.startswith("+") and not line.startswith("+++"):
                print(art.c(art.GOOD, line))
            elif line.startswith("-") and not line.startswith("---"):
                print(art.c(art.ERR, line))
            elif line.startswith("@@"):
                print(art.c(art.RUNE, line))
            else:
                print(art.dim(line))


# --------------------------------------------------------------------------- #
# repo map (SPEC §6) — compact, token-bounded
# --------------------------------------------------------------------------- #

def build_repomap(workspace: pathlib.Path, max_lines=60) -> str:
    import re
    out = []
    sym = re.compile(r"^\s*(def|class|function|export\s+(?:default\s+)?(?:function|const))\s+([A-Za-z_]\w*)")
    count = 0
    for p in sorted(workspace.rglob("*")):
        if count >= max_lines:
            out.append("…(truncated)")
            break
        if p.is_dir() or any(part in toolmod._IGNORE or part.startswith(".")
                             for part in p.relative_to(workspace).parts):
            continue
        if p.suffix not in (".py", ".js", ".ts", ".go", ".rb", ".java"):
            continue
        rel = p.relative_to(workspace)
        syms = []
        try:
            for line in p.read_text(errors="ignore").splitlines():
                m = sym.match(line)
                if m:
                    syms.append(m.group(2))
        except Exception:
            pass
        out.append(f"{rel} ({', '.join(syms[:8])})" if syms else str(rel))
        count += 1
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# permission gate (SPEC §4A boundary)
# --------------------------------------------------------------------------- #

class Cancelled(Exception):
    pass


class Session:
    def __init__(self, cfg, backend, confirm=None, ui=None):
        self.cfg = cfg
        self.backend = backend
        self.ui = ui or UI(cfg.verbosity)
        self.store = storemod.Store(cfg.workspace)
        self.ctx = toolmod.ToolContext(
            workspace=cfg.workspace,
            web_enabled=cfg.web_enabled,
            docker_enabled=cfg.docker_enabled,
            store=self.store,
        )
        self.registry = toolmod.build_registry(self.ctx)
        self.confirm = confirm or self._default_confirm
        self.messages = [{"role": "system", "content": self._system()}]
        # when a host (TUI) drives the UI it manages its own spinner/cancel
        self.use_stdout_spinner = ui is None
        self.steer_on_cancel = ui is None
        self.cancel_event = threading.Event()
        self.session_id = storemod.Store.new_id()
        self.title = ""
        self.steps = 0          # steps taken in the latest run (for the status line)

    def current_tokens(self) -> int:
        return self.est_tokens(self.messages)

    # ---- persistence (SPEC §8) -------------------------------------------
    def _save(self):
        try:
            self.store.save_session(self.session_id, self.messages,
                                    {"title": self.title, "model": self.cfg.model,
                                     "backend": self.cfg.backend})
        except Exception:
            pass

    def resume(self, data: dict):
        """Reload a saved session's transcript (keeps the fresh system prompt)."""
        msgs = data.get("messages", [])
        kept = [m for m in msgs if m.get("role") != "system"]
        self.messages = [{"role": "system", "content": self._system()}] + kept
        self.session_id = data.get("id", self.session_id)
        self.title = data.get("meta", {}).get("title", "")
        return len(kept)

    # ---- prompt assembly --------------------------------------------------
    def _system(self):
        policy = ""
        if self.cfg.read_only:
            policy = ("PERMISSION: read-only session. Any write or command tool "
                      "WILL be refused by the runtime — answer/read only.")
        elif not self.cfg.allow_writes:
            policy = ("PERMISSION: edits and commands need the user's approval "
                      "before they run; propose them normally.")
        repomap = build_repomap(self.cfg.workspace)
        tools_block = toolmod.render_tools_block(self.registry)
        memory = self.store.render_memory() if getattr(self, "store", None) else ""
        return prompt.build_system(tools_block, str(self.cfg.workspace), repomap,
                                   policy, memory=memory, persona=self.cfg.persona,
                                   user_name=self.cfg.user_name)

    # ---- gating -----------------------------------------------------------
    def _default_confirm(self, tool, args):
        if not sys.stdin.isatty():
            return True  # piped/non-interactive: proceed (use --read-only to forbid)
        kind = "run" if tool.exec else "apply edit"
        ans = input(art.c(art.WARN, f"  ↳ {kind} with {tool.name}? [Y/n] ")).strip().lower()
        return ans in ("", "y", "yes")

    def _gate(self, tool, args):
        """Return 'allow' | 'deny' | 'preview'."""
        if not (tool.mutates or tool.exec):
            return "allow"
        if self.cfg.read_only:
            return "deny"
        if self.cfg.dry_run:
            return "preview"
        if self.cfg.allow_writes:
            return "allow"
        return "allow" if self.confirm(tool, args) else "deny"

    # ---- tool execution ---------------------------------------------------
    def _exec_tool(self, call):
        name = call.get("name")
        args = {k: v for k, v in call.items() if k != "name"}
        tool = self.registry.get(name)
        if not tool:
            return f"error: unknown tool '{name}'"

        gate = self._gate(tool, args)
        if gate == "deny":
            if self.cfg.read_only:
                return (f"refused: '{name}' would modify/execute, but this is a "
                        f"read-only session.")
            return f"skipped by user: '{name}'"
        if gate == "preview":
            return f"[dry-run] would call {name}({_summ(args)}) — no change made"

        before = None
        path = args.get("path")
        if tool.mutates and path:
            p = self.ctx.workspace / path
            before = p.read_text(errors="ignore") if p.exists() else ""
        try:
            result = tool.run(self.ctx, args)
        except toolmod.ToolError as e:
            return f"error: {e}"
        except KeyboardInterrupt:
            raise Cancelled()
        except Exception as e:
            return f"error: {type(e).__name__}: {e}"

        # show the diff for edits (SPEC §11A: diffs always)
        if tool.mutates and path:
            p = self.ctx.workspace / path
            after = p.read_text(errors="ignore") if p.exists() else ""
            self.ui.diff(toolmod._rel(self.ctx, p.resolve()), before, after)
        return result

    # ---- message assembly -------------------------------------------------
    def _user_message(self, task: str, images=None):
        """Build a user turn. With images, use the OpenAI/OpenRouter vision
        content-array form so Qwen3.6's vision path receives the screenshots."""
        if not images:
            return {"role": "user", "content": task}
        import base64
        parts = [{"type": "text", "text": task or "(see image)"}]
        for img in images:
            b64 = base64.b64encode(img).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:image/png;base64,{b64}"}})
        return {"role": "user", "content": parts}

    # ---- main loop --------------------------------------------------------
    def run(self, task: str, images=None):
        self.ctx.journal.clear()
        self.ctx.side_effects.clear()
        self.cancel_event.clear()
        if not self.title and task:
            self.title = task[:60]
        self.messages.append(self._user_message(task, images))
        steps = 0
        recent = []       # signatures of recent calls, for stuck detection
        last_error = False  # did the previous step's observation fail?
        try:
            while steps < self.cfg.max_steps:
                if self.cancel_event.is_set():
                    return self._on_cancel()
                steps += 1
                self.steps = steps
                verbose = self.cfg.verbosity == "verbose"
                spin = art.Spinner() if (not verbose and self.use_stdout_spinner) else None
                if spin:
                    spin.start()
                self._set_busy(True)
                # Adaptive reasoning (SPEC §3): think only when it pays — the first
                # step (planning) and after an error/stuck (debugging). Routine tool
                # steps run think-off, which is far cheaper and faster on a 27B.
                think_step = self.cfg.think and (steps == 1 or last_error)
                try:
                    out = self.backend.generate(
                        self.messages,
                        stop=["</tool>", "</tool_call>"],
                        max_tokens=1500,
                        temperature=self.cfg.temperature,
                        think=think_step,
                        on_token=(self._stream if verbose else None),
                    )
                except backendmod.Aborted:
                    return self._on_cancel()
                finally:
                    if spin:
                        spin.stop()
                    self._set_busy(False)
                if self.cancel_event.is_set():
                    return self._on_cancel()
                if not parser.has_tool_call(out):
                    # final answer
                    self.ui.final(out)
                    self.messages.append({"role": "assistant", "content": out})
                    if self.cfg.review:
                        self._review()
                    self._report_side_effects()
                    self._save()
                    return out

                call, err = parser.parse_tool_call(out)
                pre = re.split(r"<tool|`|\b\w+\s*\(", out)[0]
                self.ui.thought(pre)
                if err:
                    obs = f"error: {err}. Re-emit one valid <tool> block."
                    self.ui.tool("parse", "", err, ok=False)
                    assistant_text = out
                    last_error = True
                else:
                    obs = self._exec_tool(call)
                    ok = not obs.startswith(("error", "refused", "skipped"))
                    last_error = not ok
                    self.ui.tool(call.get("name", "?"), _summ(
                        {k: v for k, v in call.items() if k != "name"}),
                        obs.splitlines()[0][:80], ok=ok)
                    # normalize history to the canonical format (reinforces it,
                    # keeps token cost stable regardless of dialect the model used)
                    assistant_text = _render_call(call)

                    # stuck detection: same call repeated, or repeated errors
                    sig = json.dumps(call, sort_keys=True)
                    recent.append((sig, ok))
                    recent = recent[-4:]
                    if not ok and recent.count((sig, False)) >= 2:
                        obs += ("\n[stuck] You have tried this exact call and it "
                                "failed before. Do something DIFFERENT: read the "
                                "file/lines first, or use a different tool. Include "
                                "every required field (e.g. 'text').")
                    elif len([1 for _, o in recent if not o]) >= 3:
                        obs += ("\n[stuck] Several calls in a row failed. Step back: "
                                "re-read the relevant lines and reconsider the approach.")

                self.messages.append({"role": "assistant", "content": assistant_text})
                self.messages.append({"role": "user", "content": f"<obs>{obs}</obs>"})
                self._trim_context()
                self._save()

            self.ui.info(f"step budget ({self.cfg.max_steps}) reached.")
            return None
        except (KeyboardInterrupt, Cancelled):
            return self._on_cancel()

    def _stream(self, tok):
        sys.stdout.write(art.dim(tok))
        sys.stdout.flush()

    # ---- token economy (SPEC §6 / M3) ------------------------------------
    @staticmethod
    def _text_of(m) -> str:
        c = m.get("content", "")
        if isinstance(c, list):
            return " ".join(p.get("text", "[image]") for p in c)
        return c

    @staticmethod
    def est_tokens(messages) -> int:
        return sum(len(Session._text_of(m)) for m in messages) // 4

    def _trim_context(self):
        """Keep system + original task + the recent turns in full; collapse the
        middle into a one-line-per-step digest when we exceed the live budget.
        This is what lets long agentic loops run without the prompt ballooning."""
        budget = int(self.cfg.ctx_len * 0.6)
        if self.est_tokens(self.messages) <= budget:
            return
        keep_tail = 8                       # last ~4 turns verbatim
        if len(self.messages) <= 2 + keep_tail:
            return
        head, tail = self.messages[:2], self.messages[-keep_tail:]
        middle = self.messages[2:-keep_tail]
        digest = []
        for m in middle:
            t = self._text_of(m)
            if m["role"] == "assistant" and "<tool>" in t:
                try:
                    call = json.loads(t.split("<tool>", 1)[1].split("</tool>", 1)[0])
                    args = {k: v for k, v in call.items() if k != "name"}
                    digest.append(f"· {call.get('name')} {_summ(args)}")
                except Exception:
                    digest.append("· (tool call)")
            elif t.startswith("<obs>"):
                first = t[5:].split("</obs>")[0].splitlines()[0][:90]
                digest.append(f"  → {first}")
        note = {"role": "system",
                "content": "[earlier steps, condensed to save context]\n"
                           + "\n".join(digest[-40:])}
        self.messages = head + [note] + tail

    def _set_busy(self, busy):
        fn = getattr(self.ui, "set_busy", None)
        if fn:
            fn(busy)

    def cancel(self):
        """Cancel the run now — aborts the in-flight request and stops the loop."""
        self.cancel_event.set()
        try:
            self.backend.abort()
        except Exception:
            pass

    # ---- cancel / steer (SPEC §7A) ---------------------------------------
    def _on_cancel(self):
        self.ui.info("⏹ interrupted — session kept.")
        if not self.steer_on_cancel or not sys.stdin.isatty():
            return None
        nxt = input(art.c(art.WARN,
            "  new instruction (enter=resume, 'u'=undo, 'q'=quit): ")).strip()
        if nxt.lower() == "q":
            raise KeyboardInterrupt
        if nxt.lower() == "u":
            print(self.undo())
            return None
        if nxt:
            return self.run(nxt)
        return self.run("continue.")

    # ---- review (SPEC §11B) ----------------------------------------------
    def _review(self):
        diff = self._run_diff()
        if not diff.strip():
            return
        self.ui.info("\n— review —")
        review_msgs = [
            {"role": "system", "content":
             "You are reviewing a code change. Report ONLY concrete issues: "
             "missed edge cases, leftover debug code, out-of-scope edits, bugs. "
             "Be terse. Do not suggest tool calls; this is read-only."},
            {"role": "user", "content": f"Review this diff:\n{diff}"},
        ]
        out = self.backend.generate(review_msgs, max_tokens=600,
                                    temperature=0.2, think=True)
        self.ui.final(out)

    def _run_diff(self):
        chunks = []
        seen = {}
        for path, old in self.ctx.journal:
            seen.setdefault(path, old)  # keep earliest pre-run state
        for path, old in seen.items():
            new = path.read_text(errors="ignore") if path.exists() else ""
            rel = toolmod._rel(self.ctx, path)
            d = "\n".join(difflib.unified_diff(
                (old or "").splitlines(), new.splitlines(),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
            if d:
                chunks.append(d)
        return "\n".join(chunks)

    # ---- undo (SPEC §7A) --------------------------------------------------
    def undo(self):
        if not self.ctx.journal:
            return "nothing to undo."
        restored = []
        for path, old in reversed(self.ctx.journal):
            if old is None:
                if path.exists():
                    path.unlink()
                    restored.append(f"removed {toolmod._rel(self.ctx, path)}")
            else:
                path.write_text(old)
                restored.append(f"reverted {toolmod._rel(self.ctx, path)}")
        self.ctx.journal.clear()
        msg = "undo: " + ", ".join(restored)
        if self.ctx.side_effects:
            msg += ("\nnote: these side effects were NOT reverted: "
                    + "; ".join(self.ctx.side_effects))
        return msg

    def _report_side_effects(self):
        if self.ctx.side_effects:
            self.ui.info("side effects (not auto-undoable): "
                         + "; ".join(self.ctx.side_effects))


def _render_call(call: dict) -> str:
    """Canonical wire form: JSON metadata + a <text> block for any file body.
    Mirrors the protocol we ask the model to use, so history stays consistent."""
    text_key = next((k for k in ("text", "content", "new_text", "code") if k in call), None)
    if text_key is None:
        return "<tool>\n" + json.dumps(call) + "\n</tool>"
    meta = {k: v for k, v in call.items() if k != text_key}
    return ("<tool>\n" + json.dumps(meta) + "\n<text>\n"
            + str(call[text_key]) + "\n</text>\n</tool>")


def _summ(args: dict) -> str:
    parts = []
    for k, v in args.items():
        sv = str(v).replace("\n", "⏎")
        if len(sv) > 30:
            sv = sv[:30] + "…"
        parts.append(sv if k in ("path", "cmd", "query", "name") else f"{k}={sv}")
    return " ".join(parts)
