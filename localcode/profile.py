"""Auto-generated project profile (SPEC §8 — "learn the project once").

A cheap, LLM-free scan that detects language, test command, entry points and
dependency files, written to .localcode/PROFILE.md and loaded compactly into the
system prompt. This means the agent doesn't burn tokens re-deriving how to run
or where things live every session.
"""
from __future__ import annotations

import pathlib
import collections

_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", ".localcode",
           "dist", "build", ".mypy_cache", ".pytest_cache", ".idea"}

_LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".java": "Java", ".c": "C", ".cpp": "C++",
    ".sh": "Shell",
}

_DEP_FILES = ["requirements.txt", "pyproject.toml", "setup.py", "package.json",
              "go.mod", "Cargo.toml", "Gemfile", "pom.xml"]

_ENTRY_CANDIDATES = ["__main__.py", "main.py", "app.py", "manage.py",
                     "index.js", "server.py", "cli.py", "main.go"]


def _iter_files(ws: pathlib.Path):
    for p in ws.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _IGNORE or part.startswith(".") for part in p.relative_to(ws).parts):
            continue
        yield p


def detect_test_cmd(ws: pathlib.Path) -> str:
    if any(ws.rglob("test_*.py")) or any(ws.rglob("*_test.py")) or (ws / "tests").is_dir():
        from .tools import PY_EXE
        return f"{PY_EXE} -m pytest -q"
    pkg = ws / "package.json"
    if pkg.exists() and '"test"' in pkg.read_text(errors="ignore"):
        return "npm test"
    if any(ws.rglob("*_test.go")):
        return "go test ./..."
    mk = ws / "Makefile"
    if mk.exists() and "test:" in mk.read_text(errors="ignore"):
        return "make test"
    return ""


def build_profile(workspace) -> str:
    ws = pathlib.Path(workspace)
    langs = collections.Counter()
    n = 0
    for p in _iter_files(ws):
        lang = _LANG_BY_EXT.get(p.suffix)
        if lang:
            langs[lang] += 1
        n += 1
        if n > 4000:
            break
    top_langs = ", ".join(f"{l}" for l, _ in langs.most_common(3)) or "unknown"

    deps = [f for f in _DEP_FILES if (ws / f).exists()]
    entries = [f for f in _ENTRY_CANDIDATES if any(ws.rglob(f))][:4]
    top_dirs = sorted(
        d.name for d in ws.iterdir()
        if d.is_dir() and d.name not in _IGNORE and not d.name.startswith("."))[:10]
    test_cmd = detect_test_cmd(ws)

    lines = ["# Project profile (auto-detected)", ""]
    lines.append(f"- language: {top_langs}")
    if test_cmd:
        lines.append(f"- run tests: `{test_cmd}`")
    if entries:
        lines.append(f"- entry points: {', '.join(entries)}")
    if deps:
        lines.append(f"- dependencies: {', '.join(deps)}")
    if top_dirs:
        lines.append(f"- top-level dirs: {', '.join(top_dirs)}")
    return "\n".join(lines)
