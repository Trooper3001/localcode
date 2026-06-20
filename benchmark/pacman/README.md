# Benchmark: Pac-Man, four agents, one model

Same task ("build a playable browser Pac-Man clone"), same model
(`qwen/qwen3.6-27b`), run separately against four different terminal coding
agents in fresh project directories. No prompt tuning per agent — whatever
each agent's default scaffolding/system prompt does with the task is what
shipped.

| Agent | Output | Runs out of the box? | Result |
|---|---|---|---|
| [Qwen Code](https://github.com/QwenLM/qwen-code) | [`qwen-code/`](qwen-code/index.html) — single 14&nbsp;KB HTML file | Yes, `file://` | Playable, full ghost AI, particles, screen-shake. One cosmetic HUD bug (lives rendered as literal `<font>` text instead of hearts — `fontcolor()` result assigned to `.textContent`). |
| [opencode](https://github.com/opencode-ai/opencode) | [`opencode/`](opencode/pacman.html) — single 22&nbsp;KB HTML file | Yes, `file://` | **Crashes on start.** Clicking "Start" throws `Uncaught TypeError` and the render loop dies after one frame — Pac-Man and all ghosts freeze permanently at spawn. Likely a malformed row in the hand-typed ASCII maze causing an out-of-bounds tile lookup. Best-looking static UI chrome (header/footer, gradient button) of the three, but the game itself never becomes playable. |
| [pi](https://pi.dev) | [`pi/`](pi/pacman.html) — single 21&nbsp;KB HTML file | Yes, `file://` | Mostly playable — moves, eats dots/power-pellets, scores correctly, ghosts release from the house in sequence, no console errors. **But Pac-Man's sprite breaks on Up**: when blocked (or generally facing up), the mouth-arc rendering math flips and draws a malformed/backwards wedge instead of a normal upward-facing Pac-Man. |
| localcode | [`localcode/`](localcode/index.html) — modular: `index.html` + `game/{data,engine,renderer,main}.js` | Needs `http://` (ES modules are CORS-blocked on `file://`) | Playable once served. No console errors. Most complete ghost AI (distinct Blinky/Pinky/Inky/Clyde targeting, frightened/eaten states, scatter/chase cycling) and the only one split into clean, separately-responsible modules. Known issue: ghost movement isn't fully correct. |

## How it was checked

Each build was opened in a real browser (Chrome via chrome-devtools-mcp),
console errors were checked, and the game was actually started and driven
with keypresses — not just read as source. localcode's build needed a
one-off local HTTP server (`python3 -m http.server`) to get a fair test, since
`type="module"` scripts are blocked under the `file://` origin; this isn't a
logic bug, it's a packaging/deployment characteristic worth knowing about.

## Caveats

- Sample size of one prompt/one game — not a rigorous benchmark, just a
  spot-check. Any one agent's bugs here could be non-representative.
- The bugs found aren't equally severe — opencode's output never becomes
  playable; qwen-code and pi are fully playable with one visible-but-survivable
  bug each; localcode's ghost movement issue affects the AI, not whether the
  game runs at all.
- localcode's build is the only one that requires a server rather than a bare
  double-clicked HTML file, which is a real ergonomics cost regardless of
  whether the underlying code is correct.

## Takeaway

All four produced *something* playable except opencode, which never recovers
from its crash. The other three each shipped with a real bug: a cosmetic HUD
glitch (qwen-code), a broken upward-facing sprite (pi), and incorrect ghost
movement (localcode). None of the four is bug-free — this is one prompt, one
data point. Repeating it across several different prompts would be the real
test.
