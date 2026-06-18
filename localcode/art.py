"""Cthulhu-themed terminal aesthetics for localcode.

Inspired by OpenCode's TUI (block-letter logo, braille spinner, a bidirectional
"Knight Rider" scanner) — reimagined eldritch. Stdlib-only: raw ANSI, no deps.
"""
from __future__ import annotations

import sys
import time
import threading
import itertools


# --------------------------------------------------------------------------- #
# palette — abyssal greens fading to void purple
# --------------------------------------------------------------------------- #

def _truecolor():
    return sys.stdout.isatty() and "256color" not in "" and "TERM" != "dumb"


def rgb(r, g, b, s):
    if not sys.stdout.isatty():
        return s
    return f"\033[38;2;{r};{g};{b}m{s}\033[0m"


# eldritch gradient stops (arcane glow → deep violet) — kept bright enough to
# stay legible on a black terminal (no near-black stops)
ABYSS = [
    (208, 178, 255),  # pale arcane glow
    (182, 138, 255),  # bright violet
    (158, 110, 246),  # amethyst
    (140, 92, 224),   # royal void
    (124, 80, 205),   # deep violet
    (112, 72, 190),   # abyssal violet
]

ACCENT = (180, 140, 255)   # bright violet — primary
MUTED = (165, 158, 188)    # readable light mauve-grey (was too dark)
WARN = (240, 198, 92)      # amber
ERR = (246, 118, 158)      # blood-rose
RUNE = (201, 170, 255)     # arcane glow
GOOD = (124, 232, 160)     # phosphor green (diffs/success) — brighter
PLAIN = (228, 228, 240)    # near-white body text


def c(color, s):
    return rgb(*color, s)


def dim(s):
    return c(MUTED, s)


# --------------------------------------------------------------------------- #
# the idol — Cthulhu ASCII banner
# --------------------------------------------------------------------------- #

_IDOL = r"""
      ▄▄████████▄▄
    ▟██▀▀░░░░░░▀▀██▙
   ██▘  ▟██▙ ▟██▙  ▝██
   ██   ▜██▛ ▜██▛   ██
   ▜█▖     ▼▼     ▗█▛
    ▜██▄▖ ▗▆▆▆▖ ▄▟██▛
      ▀▀██▙▟███▙▟██▀▀
       ╲ ╲┃╲┃┃╱┃╱ ╱
        ╲╲┃ ┃┃ ┃╱╱
         ╲┃ ┃┃ ┃╱
          ╲╮┃┃╭╱
           ╰┛┗╯
"""

_WORDMARK = [
    "█   █▀█ █▀▀ █▀█ █   █▀▀ █▀█ █▀▄ █▀▀",
    "█   █ █ █   █▀█ █   █   █ █ █ █ █▀▀",
    "█▄▄ █▄█ █▄▄ █ █ █▄▄ █▄▄ █▄█ █▄▀ █▄▄",
]

TAGLINE = "the code-summoner · qwen3.6 · runs in the deep, runs local"


def banner(subtitle: str = "") -> str:
    lines = []
    idol = _IDOL.strip("\n").splitlines()
    n = len(idol)
    for i, line in enumerate(idol):
        col = ABYSS[min(int(i / max(1, n) * len(ABYSS)), len(ABYSS) - 1)]
        lines.append(c(col, line))
    lines.append("")
    for j, w in enumerate(_WORDMARK):
        lines.append(c(ABYSS[min(j, len(ABYSS) - 1)], "   " + w))
    lines.append("")
    lines.append("   " + dim(TAGLINE))
    if subtitle:
        lines.append("   " + dim(subtitle))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# spinners — writhing in the dark
# --------------------------------------------------------------------------- #

# braille swell, like a tentacle coiling
TENTACLE = ["⠁", "⠃", "⠇", "⠧", "⠷", "⠿", "⡿", "⣿", "⡿", "⠿", "⠷", "⠧", "⠇", "⠃"]
# a watching eye, opening and closing
EYE = ["·", "•", "●", "◉", "⊙", "◉", "●", "•"]
SIGILS = ["☉", "✶", "✷", "❉", "✸", "✦"]

SUMMONS = [
    "summoning",
    "whispering to R'lyeh",
    "the stars are right",
    "consulting the elder ones",
    "decoding eldritch sigils",
    "channeling the deep",
    "the dreamer stirs",
    "reading forbidden lines",
]


class Spinner:
    """A threaded, themed spinner. Use as a context manager around blocking work."""

    def __init__(self, message: str = "", frames=None, interval=0.09,
                 color=ACCENT, cycle_summons=True):
        self.frames = frames or TENTACLE
        self.interval = interval
        self.color = color
        self.message = message
        self.cycle_summons = cycle_summons and not message
        self._stop = threading.Event()
        self._thread = None
        self.enabled = sys.stdout.isatty()

    def _spin(self):
        frames = itertools.cycle(self.frames)
        summons = itertools.cycle(SUMMONS)
        msg = self.message or next(summons)
        tick = 0
        while not self._stop.is_set():
            f = next(frames)
            if self.cycle_summons and tick % 24 == 0:
                msg = next(summons)
            sys.stdout.write("\r" + c(self.color, f) + " " + dim(msg + "…") + "  ")
            sys.stdout.flush()
            tick += 1
            time.sleep(self.interval)
        # clear the line
        sys.stdout.write("\r" + " " * (len(self.message or "summoning") + 12) + "\r")
        sys.stdout.flush()

    def start(self):
        if not self.enabled:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=1)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


# --------------------------------------------------------------------------- #
# scanner — a bidirectional tentacle sweep (OpenCode's Knight Rider, eldritch)
# --------------------------------------------------------------------------- #

def scanner_frames(width=14, shapes="⬩◆⬥◆⬩"):
    """Bidirectional sweep of an arcane node with a fading trail."""
    trail = list(shapes)
    frames = []
    seq = list(range(width)) + list(range(width - 2, 0, -1))
    for head in seq:
        row = []
        for i in range(width):
            d = abs(i - head)
            row.append(trail[d] if d < len(trail) else "·")
        frames.append("".join(row))
    return frames
