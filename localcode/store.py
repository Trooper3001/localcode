"""Persistence for localcode: project memory + resumable sessions (SPEC §8).

Everything lives under `<workspace>/.localcode/`:
  memory.md            durable facts the agent/user record (loaded each session)
  PROFILE.md           generated repo profile (optional, refreshable)
  sessions/<id>.json   full transcript + metadata, for --continue / --resume
"""
from __future__ import annotations

import json
import time
import pathlib
import datetime as _dt


class Store:
    def __init__(self, workspace: pathlib.Path):
        self.root = pathlib.Path(workspace) / ".localcode"
        self.sessions_dir = self.root / "sessions"
        self.memory_file = self.root / "memory.md"
        self.profile_file = self.root / "PROFILE.md"

    def ensure(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    # ---- memory -----------------------------------------------------------
    def load_memory(self) -> list[str]:
        if not self.memory_file.exists():
            return []
        out = []
        for line in self.memory_file.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("- "):
                out.append(line[2:].strip())
            elif line and not line.startswith("#"):
                out.append(line)
        return out

    def add_memory(self, fact: str) -> bool:
        fact = fact.strip().replace("\n", " ")
        if not fact:
            return False
        existing = self.load_memory()
        if fact in existing:
            return False
        self.ensure()
        if not self.memory_file.exists():
            self.memory_file.write_text("# localcode project memory\n\n")
        with open(self.memory_file, "a") as f:
            f.write(f"- {fact}\n")
        return True

    def render_memory(self, limit=25) -> str:
        facts = self.load_memory()[:limit]
        if not facts:
            return ""
        return "\n".join(f"- {x}" for x in facts)

    def load_profile(self) -> str:
        return self.profile_file.read_text(errors="ignore") if self.profile_file.exists() else ""

    def save_profile(self, text: str):
        self.ensure()
        self.profile_file.write_text(text)

    # ---- sessions ---------------------------------------------------------
    @staticmethod
    def new_id() -> str:
        return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    def save_session(self, sid: str, messages: list, meta: dict):
        self.ensure()
        data = {"id": sid, "updated": time.time(), "meta": meta, "messages": messages}
        (self.sessions_dir / f"{sid}.json").write_text(json.dumps(data))

    def load_session(self, sid: str) -> dict | None:
        p = self.sessions_dir / f"{sid}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def latest_session(self) -> dict | None:
        sessions = sorted(self.sessions_dir.glob("*.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True) \
            if self.sessions_dir.exists() else []
        if not sessions:
            return None
        try:
            return json.loads(sessions[0].read_text())
        except Exception:
            return None

    def list_sessions(self, limit=20) -> list[dict]:
        if not self.sessions_dir.exists():
            return []
        out = []
        for p in sorted(self.sessions_dir.glob("*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                d = json.loads(p.read_text())
                out.append({"id": d.get("id"), "updated": d.get("updated", 0),
                            "title": d.get("meta", {}).get("title", "")})
            except Exception:
                continue
        return out
