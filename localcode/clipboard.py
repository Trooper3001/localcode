"""Grab an image from the system clipboard (for pasting screenshots into chat).

Linux: tries Wayland (wl-paste) then X11 (xclip). macOS: pngpaste / osascript.
Returns PNG bytes or None. No third-party deps.
"""
from __future__ import annotations

import sys
import shutil
import subprocess
import tempfile
import os


def _run(cmd) -> bytes | None:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=8)
    except Exception:
        return None
    if out.returncode == 0 and out.stdout[:4] == b"\x89PNG":
        return out.stdout
    return None


def grab_image() -> bytes | None:
    # Wayland
    if shutil.which("wl-paste"):
        img = _run(["wl-paste", "--type", "image/png"])
        if img:
            return img
    # X11
    if shutil.which("xclip"):
        img = _run(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"])
        if img:
            return img
    # macOS
    if sys.platform == "darwin":
        if shutil.which("pngpaste"):
            img = _run(["pngpaste", "-"])
            if img:
                return img
        # fallback via AppleScript to a temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        script = (f'try\nset f to (open for access POSIX file "{tmp}" with write permission)\n'
                  f'write (the clipboard as «class PNGf») to f\nclose access f\nend try')
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=8)
            with open(tmp, "rb") as fh:
                data = fh.read()
            os.unlink(tmp)
            if data[:4] == b"\x89PNG":
                return data
        except Exception:
            pass
    return None


def available() -> str:
    for tool in ("wl-paste", "xclip", "pngpaste"):
        if shutil.which(tool):
            return tool
    if sys.platform == "darwin":
        return "osascript"
    return ""
