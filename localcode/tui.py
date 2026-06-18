"""Full-screen terminal UI for localcode — OpenCode-style, Cthulhu-themed.

Layout:
  ┌───────────────────────────────────────────────┐
  │  header: idol mark · workspace                  │
  ├───────────────────────────────────────────────┤
  │  transcript (scrollable): prompts, tool log,    │
  │  diffs, answers                                 │
  ├───────────────────────────────────────────────┤
  │  ᛝ input line                                   │
  │  footer: status · model · step · spinner        │
  └───────────────────────────────────────────────┘

stdlib `curses` only. The agent runs in a worker thread; a thread-safe bridge
feeds styled rows into the transcript. Cancellation is cooperative (Esc/Ctrl-C
sets the session's cancel event; it stops at the next step boundary).
"""
from __future__ import annotations

import curses
import threading
import difflib
import textwrap

from . import art, tools as toolmod, clipboard
from .loop import Session, build_repomap


HELP = [
    "commands:",
    "  /yolo            toggle auto-approve (apply edits/run without asking)",
    "  /readonly        toggle hard read-only (no writes or commands)",
    "  /steps N         set the step budget   ·   /steps off  to ignore it",
    "  /think           toggle model reasoning (slower, smarter)",
    "  /web             toggle web search tools",
    "  /verbose         cycle quiet → normal → verbose",
    "  /undo            revert this run's file changes",
    "  /resume          continue the last run",
    "  /sessions        list saved sessions  ·  /load ID  to resume one",
    "  /clear           clear the transcript",
    "  /help · /quit",
    "keys: Enter=send · Ctrl-V=paste screenshot · Esc=cancel · Ctrl-Q=quit · PgUp/PgDn=scroll",
]


# style names → color-pair ids (assigned in _init_colors)
STYLES = ["plain", "accent", "good", "err", "muted", "rune", "head", "warn"]
SPIN = art.TENTACLE


class Bridge:
    """Thread-safe sink implementing the UI interface loop.Session calls."""

    def __init__(self, app):
        self.app = app
        self.verbosity = "normal"

    # -- UI protocol used by Session ---------------------------------------
    def thought(self, text):
        line = (text or "").strip().splitlines()
        line = line[0][:200] if line else ""
        import re
        if len(re.sub(r"[^A-Za-z0-9]", "", line)) < 4:
            return
        self.app.add([("  ≀ " + line, "muted")])

    def tool(self, name, arg_summary, result_summary, ok=True):
        sc = "good" if ok else "err"
        self.app.add([("◆ ", sc), (name, "accent"),
                      ("  " + arg_summary, "muted"),
                      ("    " + result_summary, sc)])

    def info(self, text):
        self.app.add([(text, "muted")])

    def final(self, text):
        self.app.add([("", "plain")])
        for para in (text or "").strip().splitlines():
            self.app.add([(para, "plain")])
        self.app.add([("", "plain")])

    def diff(self, path, old, new):
        for line in difflib.unified_diff(
                (old or "").splitlines(), (new or "").splitlines(),
                fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""):
            if line.startswith("+") and not line.startswith("+++"):
                st = "good"
            elif line.startswith("-") and not line.startswith("---"):
                st = "err"
            elif line.startswith("@@"):
                st = "rune"
            else:
                st = "muted"
            self.app.add([(line, st)])

    def set_busy(self, busy):
        self.app.busy = busy
        self.app.dirty = True

    # plain-UI compat (unused in TUI but harmless)
    def _c(self, s, code=None):
        return s


class TuiApp:
    def __init__(self, cfg, backend):
        self.cfg = cfg
        self.backend = backend
        self.bridge = Bridge(self)
        self.sess = Session(cfg, backend, confirm=self._confirm, ui=self.bridge)
        self.entries = []          # logical rows: list of (text, style)
        self.lock = threading.Lock()
        self.input = ""
        self.scroll = 0            # rows from bottom; 0 = stuck to latest
        self.busy = False
        self.dirty = True
        self.running = True
        self.worker = None
        self.spin_i = 0
        self.pending_images = []    # PNG bytes attached to the next message
        self._resume_data = None    # set by launch() if --continue/--resume
        # confirmation handshake
        self._pending = None       # (tool, args) awaiting y/n
        self._confirm_event = threading.Event()
        self._confirm_result = False

    # ---- transcript -------------------------------------------------------
    def add(self, segments):
        with self.lock:
            self.entries.append(segments)
            self.dirty = True

    def add_text(self, text, style="plain"):
        self.add([(text, style)])

    # ---- confirmation (called from worker thread) -------------------------
    def _confirm(self, tool, args):
        self._confirm_event.clear()
        self._pending = (tool, args)
        self.dirty = True
        self._confirm_event.wait()
        self._pending = None
        self.dirty = True
        return self._confirm_result

    # ---- agent run --------------------------------------------------------
    def _submit(self, text):
        images = self.pending_images
        self.pending_images = []
        tag = f"  [{len(images)} image]" if images else ""
        self.add([("ᛝ ", "accent"), (text, "plain"), (tag, "muted")])
        self.scroll = 0

        def work():
            try:
                self.sess.run(text, images=images or None)
            except Exception as e:
                self.add([(f"error: {type(e).__name__}: {e}", "err")])
            self.busy = False
            self.dirty = True

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    @property
    def working(self):
        return self.worker is not None and self.worker.is_alive()

    # ---- curses lifecycle -------------------------------------------------
    def run(self):
        curses.wrapper(self._main)

    def _init_colors(self):
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        bg = -1
        # truecolor-ish purples if the terminal allows custom colors
        custom = curses.can_change_color() and curses.COLORS >= 16
        palette = {
            "accent": (art.ACCENT, curses.COLOR_MAGENTA),
            "good": (art.GOOD, curses.COLOR_GREEN),
            "err": (art.ERR, curses.COLOR_RED),
            "muted": (art.MUTED, curses.COLOR_WHITE),
            "rune": (art.RUNE, curses.COLOR_MAGENTA),
            "head": (art.ABYSS[1], curses.COLOR_MAGENTA),
            "warn": (art.WARN, curses.COLOR_YELLOW),
            "plain": ((220, 220, 230), curses.COLOR_WHITE),
        }
        self.pair = {}
        idx = 16
        for i, name in enumerate(STYLES, start=1):
            rgb, fallback = palette[name]
            fg = fallback
            if custom and idx < curses.COLORS:
                r, g, b = [int(v / 255 * 1000) for v in rgb]
                try:
                    curses.init_color(idx, r, g, b)
                    fg = idx
                    idx += 1
                except curses.error:
                    fg = fallback
            curses.init_pair(i, fg, bg)
            self.pair[name] = curses.color_pair(i)
            if name == "muted":
                self.pair[name] |= curses.A_DIM

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(1)
        stdscr.nodelay(True)
        stdscr.timeout(80)
        self._init_colors()
        self._greet()
        while self.running:
            self._draw()
            try:
                ch = stdscr.get_wch()
            except curses.error:
                ch = None  # timeout tick (drives the spinner)
            if ch is not None:
                self._handle(ch)
            if self.busy or self.working:
                self.spin_i += 1
                self.dirty = True

    def _greet(self):
        for ln in art.banner().splitlines():
            # strip ANSI; curses can't render it. Color the whole line as head.
            import re
            clean = re.sub(r"\033\[[0-9;]*m", "", ln)
            self.add([(clean, "head")])
        self.add([("", "plain")])
        self.add([("the dreamer waits. speak your task.  /help for rites · "
                   "Ctrl-V paste screenshot · Esc cancel · Ctrl-Q quit", "muted")])
        self.add([("", "plain")])
        if self._resume_data:
            n = self.sess.resume(self._resume_data)
            self.add([(f"↺ resumed session {self._resume_data.get('id')} "
                       f"({n} messages restored)", "rune")])
            # replay the gist so the user sees context
            for m in self._resume_data.get("messages", [])[-6:]:
                role = m.get("role")
                txt = self.sess._text_of(m)
                if role == "user" and not txt.startswith("<obs>"):
                    self.add([("ᛝ ", "accent"), (txt[:120], "plain")])
            self.add([("", "plain")])

    # ---- input handling ---------------------------------------------------
    def _handle(self, ch):
        if isinstance(ch, str):
            if ch == "\x11":              # Ctrl-Q
                self.running = False
            elif ch == "\x1b":            # Esc → cancel current run / confirm
                if self._pending:
                    self._confirm_result = False
                    self._confirm_event.set()
                elif self.working:
                    self.sess.cancel()
            elif ch in ("\n", "\r"):
                self._on_enter()
            elif ch in ("\x7f", "\b"):    # backspace
                self.input = self.input[:-1]
            elif ch == "\x15":            # Ctrl-U clear line
                self.input = ""
            elif ch == "\x16":            # Ctrl-V paste screenshot
                self._paste_image()
            elif ch.isprintable():
                if self._pending:
                    self._answer_confirm(ch)
                else:
                    self.input += ch
            self.dirty = True
            return
        # special keys (int)
        if ch == curses.KEY_BACKSPACE:
            self.input = self.input[:-1]
        elif ch == curses.KEY_PPAGE:
            self.scroll += 5
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 5)
        elif ch == curses.KEY_UP:
            self.scroll += 1
        elif ch == curses.KEY_DOWN:
            self.scroll = max(0, self.scroll - 1)
        self.dirty = True

    def _answer_confirm(self, ch):
        if ch.lower() == "y":
            self._confirm_result = True
            self._confirm_event.set()
        elif ch.lower() == "n":
            self._confirm_result = False
            self._confirm_event.set()

    def _paste_image(self):
        img = clipboard.grab_image()
        if img:
            self.pending_images.append(img)
            self.add([(f"📎 screenshot attached ({len(img)//1024} KB) — "
                       f"type a question and Enter", "rune")])
        else:
            tool = clipboard.available()
            hint = f"(have {tool}; copy an image first)" if tool else \
                "(install wl-paste/xclip to paste images)"
            self.add([(f"no image in clipboard {hint}", "warn")])

    def _cmd(self, text) -> bool:
        """Handle a /command. Returns True if it was a command."""
        if not text.startswith("/"):
            return False
        parts = text.split()
        cmd, arg = parts[0], (parts[1] if len(parts) > 1 else "")
        if cmd in ("/quit", "/exit", "/q"):
            self.running = False
        elif cmd == "/help":
            self.add([("", "plain")])
            for l in HELP:
                self.add([(l, "muted")])
        elif cmd == "/undo":
            self.add([(self.sess.undo(), "warn")])
        elif cmd == "/resume":
            if not self.working:
                self._submit("continue.")
        elif cmd == "/clear":
            with self.lock:
                self.entries.clear()
            self.scroll = 0
        elif cmd == "/sessions":
            rows = self.sess.store.list_sessions()
            if not rows:
                self.add([("no saved sessions yet.", "muted")])
            for r in rows:
                self.add([(f"  {r['id']}", "accent"), (f"  {r['title']}", "muted")])
        elif cmd == "/load":
            data = self.sess.store.load_session(arg) if arg else None
            if not data:
                self.add([(f"no session '{arg}' (see /sessions)", "err")])
            else:
                n = self.sess.resume(data)
                self.add([(f"↺ loaded {arg} ({n} messages)", "rune")])
        elif cmd == "/yolo":
            self.cfg.allow_writes = not self.cfg.allow_writes
            self.sess.messages[0]["content"] = self.sess._system()
            self.add([(f"yolo (auto-approve) = {self.cfg.allow_writes}", "warn")])
        elif cmd == "/readonly":
            self.cfg.read_only = not self.cfg.read_only
            self.sess.messages[0]["content"] = self.sess._system()
            self.add([(f"read-only = {self.cfg.read_only}", "warn")])
        elif cmd == "/think":
            self.cfg.think = not self.cfg.think
            self.add([(f"reasoning = {self.cfg.think}", "warn")])
        elif cmd == "/web":
            self.cfg.web_enabled = not self.cfg.web_enabled
            self.sess.ctx.web_enabled = self.cfg.web_enabled
            self.sess.registry = toolmod.build_registry(self.sess.ctx)
            self.sess.messages[0]["content"] = self.sess._system()
            self.add([(f"web tools = {self.cfg.web_enabled}", "warn")])
        elif cmd == "/verbose":
            order = ["quiet", "normal", "verbose"]
            self.cfg.verbosity = order[(order.index(self.cfg.verbosity) + 1) % 3]
            self.add([(f"verbosity = {self.cfg.verbosity}", "warn")])
        elif cmd == "/steps":
            if arg.lower() in ("off", "none", "0", "∞"):
                self.cfg.max_steps = 1_000_000
                self.add([("step budget = ignored (∞)", "warn")])
            elif arg.isdigit():
                self.cfg.max_steps = int(arg)
                self.add([(f"step budget = {self.cfg.max_steps}", "warn")])
            else:
                self.add([("usage: /steps N   or   /steps off", "warn")])
        else:
            self.add([(f"unknown command {cmd} — try /help", "err")])
        return True

    def _on_enter(self):
        text = self.input.strip()
        if not text and not self.pending_images:
            return
        self.input = ""
        if self._cmd(text):
            return
        if self.working:
            self.add([("…still summoning; Esc to cancel first.", "warn")])
            return
        self._submit(text)

    # ---- rendering --------------------------------------------------------
    def _wrap(self, width):
        out = []
        with self.lock:
            entries = list(self.entries)
        for segs in entries:
            full = "".join(t for t, _ in segs)
            if not full:
                out.append([])
                continue
            # wrap while preserving the first segment's leading marker visually
            wrapped = textwrap.wrap(full, width=max(8, width), drop_whitespace=False,
                                    break_long_words=True) or [""]
            # map wrapped text back to styles by walking segment boundaries
            pos = 0
            seg_idx, seg_off = 0, 0
            for wline in wrapped:
                row = []
                remaining = len(wline)
                while remaining > 0 and seg_idx < len(segs):
                    stext, sstyle = segs[seg_idx]
                    take = min(remaining, len(stext) - seg_off)
                    row.append((stext[seg_off:seg_off + take], sstyle))
                    seg_off += take
                    remaining -= take
                    if seg_off >= len(stext):
                        seg_idx += 1
                        seg_off = 0
                out.append(row)
                pos += len(wline)
        return out

    def _draw(self):
        if not self.dirty:
            return
        self.dirty = False
        s = self.stdscr
        h, w = s.getmaxyx()
        s.erase()

        # header
        title = " ᛝ localcode "
        sub = f" {self.cfg.backend} · {self.cfg.model} "
        self._put(0, 0, [(title, "head"), ("· " + str(self.cfg.workspace), "muted")], w)
        s.hline(1, 0, curses.ACS_HLINE, w)

        top = 2
        input_row = h - 2
        foot_row = h - 1
        body_h = input_row - 1 - top
        s.hline(input_row - 1, 0, curses.ACS_HLINE, w)

        # transcript
        lines = self._wrap(w - 1)
        total = len(lines)
        end = total - self.scroll
        start = max(0, end - body_h)
        view = lines[start:end]
        y = top + max(0, body_h - len(view))
        for row in view:
            self._put(y, 0, row or [("", "plain")], w)
            y += 1

        # input line
        prompt = "ᛝ "
        if self._pending:
            tool, _ = self._pending
            kind = "run" if tool.exec else "apply edit"
            self._put(input_row, 0,
                      [(f"  {kind} with ", "warn"), (tool.name, "accent"),
                       ("?  [y/n]  (Esc=no)", "warn")], w)
        else:
            segs = [(prompt, "accent"), (self.input, "plain")]
            if self.pending_images:
                segs.append((f"  📎{len(self.pending_images)}", "rune"))
            self._put(input_row, 0, segs, w)

        # footer / status
        if self.busy or self.working:
            spin = SPIN[self.spin_i % len(SPIN)]
            status = [(f" {spin} ", "accent"), ("summoning…", "muted")]
        else:
            mode = "read-only" if self.cfg.read_only else ("yolo" if self.cfg.allow_writes else "ask")
            status = [(" ◆ ready", "good"), (f"  · {mode}", "muted")]
        # live context-budget + step counters (token economy, made visible)
        try:
            tok = self.sess.current_tokens()
        except Exception:
            tok = 0
        budget = int(self.cfg.ctx_len * 0.6)
        tcol = "warn" if tok > budget * 0.85 else "muted"
        status.append((f"  · ⟁{tok}/{budget} tok", tcol))
        status.append((f"  · step {self.sess.steps}/{self.cfg.max_steps}", "muted"))
        if self.scroll:
            status.append((f"  ↑{self.scroll}", "muted"))
        self._put(foot_row, 0, status, w)

        # place cursor at end of input
        if not self._pending:
            cx = min(w - 1, len("ᛝ ") + len(self.input))
            try:
                s.move(input_row, cx)
            except curses.error:
                pass
        s.refresh()

    def _put(self, y, x, segments, w):
        for text, style in segments:
            if x >= w - 1:
                break
            text = text[: max(0, w - 1 - x)]
            try:
                self.stdscr.addstr(y, x, text, self.pair.get(style, 0))
            except curses.error:
                pass
            x += len(text)


def launch(cfg, backend, resume=None):
    app = TuiApp(cfg, backend)
    if resume:
        data = (app.sess.store.latest_session() if resume == "latest"
                else app.sess.store.load_session(resume))
        if data:
            app._resume_data = data
    app.run()
