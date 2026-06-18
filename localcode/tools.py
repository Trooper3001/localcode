"""Tool registry + implementations (SPEC §5).

Each tool is a Tool(name, mutates, exec, sig, run). `mutates` = touches the
workspace; `exec` = runs a child process. The loop uses those flags to apply
permission gating (read is always free; write/exec is gated) — the tools
themselves just do the work. Read-only tools are always offered; write/exec
tools are offered too (the model decides what to use) but the runtime gates
their execution.

Stdlib-only. No ripgrep dependency — search falls back to grep then pure Python.
"""
from __future__ import annotations

import os
import re
import py_compile
import pathlib
import subprocess
import shutil
import signal
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable


# --------------------------------------------------------------------------- #
# context + journal
# --------------------------------------------------------------------------- #

@dataclass
class ToolContext:
    workspace: pathlib.Path
    web_enabled: bool = False
    docker_enabled: bool = True
    store: object = None     # store.Store, for the remember() tool
    # per-run change journal for /undo: list of (path, old_text_or_None)
    journal: list = field(default_factory=list)
    # side effects we executed but can't auto-undo (started containers, installs)
    side_effects: list = field(default_factory=list)
    written: set = field(default_factory=set)

    def resolve(self, user_path: str) -> pathlib.Path:
        """Confine every path to the workspace root (SPEC §11 sandbox)."""
        p = (self.workspace / user_path).resolve()
        root = self.workspace.resolve()
        if root != p and root not in p.parents:
            raise ToolError(f"path '{user_path}' escapes the workspace")
        return p

    def record_change(self, path: pathlib.Path):
        old = path.read_text(errors="ignore") if path.exists() else None
        self.journal.append((path, old))


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", ".localcode",
           "dist", "build", ".mypy_cache", ".pytest_cache"}


def _rel(ctx, p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(ctx.workspace))
    except ValueError:
        return str(p)


def _syntax_check(path: pathlib.Path) -> str:
    """Return '' if clean, else a one-line error with the offending line."""
    if path.suffix == ".py":
        try:
            py_compile.compile(str(path), doraise=True)
            return ""
        except py_compile.PyCompileError as e:
            msg = str(e).strip().splitlines()[-1]
            return msg[:200]
    return ""  # other languages: best-effort skip for now


def _clip(text: str, n: int = 2000) -> str:
    return text if len(text) <= n else text[:n] + f"\n…(+{len(text) - n} chars)"


def _text_arg(args, field="text"):
    """Pull the replacement/content text, tolerating the aliases models use."""
    for k in (field, "text", "content", "new_text", "code", "value", "body"):
        if k in args and args[k] is not None:
            return args[k]
    raise ToolError(
        f"missing '{field}': provide the replacement lines as a \"{field}\" "
        f"string field in the same tool call")


# --------------------------------------------------------------------------- #
# read-only tools
# --------------------------------------------------------------------------- #

def _list_dir(ctx, args):
    path = ctx.resolve(args.get("path", "."))
    depth = int(args.get("depth", 1))
    if not path.exists():
        raise ToolError(f"no such path: {args.get('path')}")
    lines = []

    def walk(d, prefix, lvl):
        if lvl > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name))
        except NotADirectoryError:
            return
        for e in entries:
            if e.name in _IGNORE or e.name.startswith("."):
                continue
            lines.append(f"{prefix}{e.name}{'/' if e.is_dir() else ''}")
            if e.is_dir():
                walk(e, prefix + "  ", lvl + 1)

    if path.is_dir():
        walk(path, "", 1)
    else:
        lines.append(path.name)
    return "\n".join(lines[:200]) or "(empty)"


def _read_file(ctx, args):
    path = ctx.resolve(args["path"])
    if not path.exists():
        raise ToolError(f"no such file: {args['path']}")
    text = path.read_text(errors="ignore")
    lines = text.splitlines()
    start = args.get("start")
    end = args.get("end")
    if start is None and end is None:
        # default window to keep tokens down on big files
        if len(lines) > 200:
            shown = lines[:200]
            body = "\n".join(f"{i+1}\t{l}" for i, l in enumerate(shown))
            return body + f"\n…({len(lines)-200} more lines; pass start/end)"
        start, end = 1, len(lines)
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or len(lines)))
    body = "\n".join(f"{i}\t{lines[i-1]}" for i in range(start, end + 1))
    return body or "(empty range)"


def _search(ctx, args):
    query = args["query"]
    glob = args.get("glob")
    results = []
    grep = shutil.which("grep")
    if grep:
        cmd = [grep, "-rni", "--exclude-dir=" + ",".join(_IGNORE), query, "."]
        if glob:
            cmd = [grep, "-rni", f"--include={glob}", query, "."]
        try:
            out = subprocess.run(cmd, cwd=ctx.workspace, capture_output=True,
                                 text=True, timeout=20)
            results = out.stdout.splitlines()
        except Exception:
            results = []
    if not results:  # pure-python fallback
        rx = re.compile(re.escape(query), re.I)
        for root, dirs, files in os.walk(ctx.workspace):
            dirs[:] = [d for d in dirs if d not in _IGNORE and not d.startswith(".")]
            for f in files:
                if glob and not pathlib.PurePath(f).match(glob):
                    continue
                p = pathlib.Path(root) / f
                try:
                    for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                        if rx.search(line):
                            results.append(f"{_rel(ctx, p)}:{i}: {line.strip()}")
                except Exception:
                    continue
    if not results:
        return f"no matches for '{query}'"
    return "\n".join(results[:40]) + (f"\n…(+{len(results)-40})" if len(results) > 40 else "")


# --------------------------------------------------------------------------- #
# mutating tools
# --------------------------------------------------------------------------- #

def _write_file(ctx, args):
    path = ctx.resolve(args["path"])
    text = _text_arg(args)
    ctx.record_change(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    ctx.written.add(path)
    syn = _syntax_check(path)
    n = len(text.splitlines())
    return f"wrote {_rel(ctx, path)} ({n} lines)" + (f"\nsyntax ERROR: {syn}" if syn else " · syntax clean")


def _replace_lines(ctx, args):
    path = ctx.resolve(args["path"])
    if not path.exists():
        raise ToolError(f"no such file: {args['path']}")
    text = _text_arg(args)
    lines = path.read_text(errors="ignore").splitlines()
    start, end = int(args["start"]), int(args["end"])
    if start < 1 or end > len(lines) or start > end:
        raise ToolError(f"bad range {start}-{end} (file has {len(lines)} lines)")
    ctx.record_change(path)
    new = text.splitlines()
    lines[start - 1:end] = new
    path.write_text("\n".join(lines) + "\n")
    ctx.written.add(path)
    syn = _syntax_check(path)
    return (f"replaced lines {start}-{end} ({end-start+1}→{len(new)})"
            + (f"\nsyntax ERROR: {syn}" if syn else " · syntax clean"))


def _append_file(ctx, args):
    path = ctx.resolve(args["path"])
    text = _text_arg(args)
    ctx.record_change(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(("\n" if path.exists() and path.stat().st_size else "") + text)
    ctx.written.add(path)
    syn = _syntax_check(path)
    return f"appended to {_rel(ctx, path)}" + (f"\nsyntax ERROR: {syn}" if syn else " · syntax clean")


def _replace_function(ctx, args):
    """Best-effort: replace a python def/class body by name (indent-based)."""
    path = ctx.resolve(args["path"])
    if not path.exists():
        raise ToolError(f"no such file: {args['path']}")
    name = args["name"]
    text = _text_arg(args)
    lines = path.read_text(errors="ignore").splitlines()
    pat = re.compile(rf"^(\s*)(def|class)\s+{re.escape(name)}\b")
    start_i = indent = None
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            start_i, indent = i, len(m.group(1))
            break
    if start_i is None:
        raise ToolError(f"function/class '{name}' not found in {args['path']}")
    end_i = len(lines)
    for j in range(start_i + 1, len(lines)):
        l = lines[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent:
            end_i = j
            break
    ctx.record_change(path)
    new = text.splitlines()
    lines[start_i:end_i] = new
    path.write_text("\n".join(lines) + "\n")
    ctx.written.add(path)
    syn = _syntax_check(path)
    return (f"replaced {args['name']} in {_rel(ctx, path)} (lines {start_i+1}-{end_i})"
            + (f"\nsyntax ERROR: {syn}" if syn else " · syntax clean"))


# --------------------------------------------------------------------------- #
# exec tools
# --------------------------------------------------------------------------- #

def _run(ctx, cmd, timeout, shell=True):
    try:
        proc = subprocess.run(
            cmd, cwd=ctx.workspace, capture_output=True, text=True,
            timeout=timeout, shell=shell, start_new_session=True,
        )
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    head = f"exit {proc.returncode}\n"
    return head + _clip(out.strip() or "(no output)")


def _run_command(ctx, args):
    cmd = args.get("cmd") or args.get("command") or args.get("arg") or args.get("args")
    if not cmd:
        raise ToolError("run_command needs a 'cmd' string")
    timeout = int(args.get("timeout", 60))
    # crude detection of irreversible side effects for the journal/report
    if re.search(r"\b(docker run|docker compose up|pip install|npm install|apt|apt-get install)\b", cmd):
        ctx.side_effects.append(cmd)
    return _run(ctx, cmd, timeout)


_LANG_RUN = {
    ".py": "python3", ".js": "node", ".sh": "bash", ".rb": "ruby", ".go": "go run",
}


def _run_file(ctx, args):
    path = ctx.resolve(args["path"])
    if not path.exists():
        raise ToolError(f"no such file: {args['path']}")
    runner = _LANG_RUN.get(path.suffix)
    if not runner:
        raise ToolError(f"don't know how to run {path.suffix} files")
    return _run(ctx, f"{runner} {path.name}", int(args.get("timeout", 60)))


def _docker(sub):
    def run(ctx, args):
        if not ctx.docker_enabled:
            raise ToolError("docker tools disabled")
        extra = args.get("args", "")
        cmd = f"docker {sub} {extra}".strip()
        if sub in ("run", "compose"):
            ctx.side_effects.append(cmd)
        return _run(ctx, cmd, int(args.get("timeout", 120)))
    return run


# --------------------------------------------------------------------------- #
# web tools (only registered when web_enabled)
# --------------------------------------------------------------------------- #

def _remember(ctx, args):
    fact = (args.get("fact") or args.get("text") or args.get("note")
            or args.get("arg") or args.get("value"))
    if not fact:
        raise ToolError("remember needs a 'fact' string")
    if ctx.store is None:
        return "noted (no store configured)"
    added = ctx.store.add_memory(fact)
    return "remembered" if added else "already knew that"


def _web_search(ctx, args):
    q = urllib.parse.quote(args["query"])
    url = f"https://duckduckgo.com/html/?q={q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15).read().decode(errors="ignore")
    except Exception as e:
        raise ToolError(f"web_search failed: {e}")
    hits = re.findall(r'result__a[^>]*>(.*?)</a>', html)[:5]
    hits = [re.sub("<.*?>", "", h).strip() for h in hits]
    return "\n".join(f"- {h}" for h in hits) or "no results"


def _web_fetch(ctx, args):
    url = args["url"]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=20).read().decode(errors="ignore")
    except Exception as e:
        raise ToolError(f"web_fetch failed: {e}")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.I)
    text = re.sub("<.*?>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _clip(text, int(args.get("max_chars", 3000)))


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

@dataclass
class Tool:
    name: str
    mutates: bool
    exec: bool
    sig: str          # compact one-line signature for the prompt
    run: Callable


def build_registry(ctx: ToolContext) -> dict[str, Tool]:
    tools = [
        Tool("list_dir", False, False, "list_dir(path='.', depth=1) — list directory", _list_dir),
        Tool("read_file", False, False, "read_file(path, start?, end?) — read a line window", _read_file),
        Tool("search", False, False, "search(query, glob?) — grep the repo", _search),
        Tool("write_file", True, False, "write_file(path, text) — create/overwrite a file", _write_file),
        Tool("replace_lines", True, False, "replace_lines(path, start, end, text) — surgical edit", _replace_lines),
        Tool("replace_function", True, False, "replace_function(path, name, text) — replace a def/class", _replace_function),
        Tool("append_file", True, False, "append_file(path, text) — append text", _append_file),
        Tool("run_command", False, True, "run_command(cmd, timeout=60) — run a shell command", _run_command),
        Tool("run_file", False, True, "run_file(path, timeout=60) — execute a source file", _run_file),
        Tool("remember", False, False, "remember(fact) — save a durable project fact for future sessions", _remember),
    ]
    if ctx.docker_enabled:
        tools += [
            Tool("docker_ps", False, True, "docker_ps(args?) — list containers", _docker("ps")),
            Tool("docker_build", True, True, "docker_build(args) — build an image", _docker("build")),
            Tool("docker_run", False, True, "docker_run(args) — run a container", _docker("run")),
            Tool("docker_logs", False, True, "docker_logs(args) — container logs", _docker("logs")),
            Tool("docker_compose", True, True, "docker_compose(args) — compose up/down", _docker("compose")),
        ]
    if ctx.web_enabled:
        tools += [
            Tool("web_search", False, False, "web_search(query) — search the web", _web_search),
            Tool("web_fetch", False, False, "web_fetch(url, max_chars?) — fetch a page as text", _web_fetch),
        ]
    return {t.name: t for t in tools}


def render_tools_block(registry: dict[str, Tool]) -> str:
    return "\n".join(f"- {t.sig}" for t in registry.values())
