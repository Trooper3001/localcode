"""A pretty terminal calculator with a retro-pretty UI."""

import sys
import math
from datetime import datetime


def clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def box(title: str, width: int = 40):
    top = f"╔{'═' * width}╗"
    mid = f"║ {title:^{width}} ║"
    bot = f"╚{'═' * width}╚"
    return top, mid, bot


def render(display: str, history: list[str]):
    w = 40
    top, mid, bot = box("  🧮 Calculator", w)

    lines = [top, mid, "║" + " " * w + "║"]

    # History (last 5)
    for entry in history[-5:]:
        lines.append(f"║ {entry:<{w}} ║")

    lines.append("║" + "─" * w + "║")

    # Current expression
    display_str = display if display else "0"
    lines.append(f"║ {display_str:<{w}} ║")
    lines.append("║" + " " * w + "║")

    # Keypad
    keypad = [
        ["7", "8", "9", "/"],
        ["4", "5", "6", "*"],
        ["1", "2", "3", "-"],
        ["C", "0", "=", "+"],
    ]
    for row in keypad:
        cells = " ".join(f"[{k:^3}]" for k in row)
        lines.append(f"║ {cells:^{w}} ║")

    lines.append(bot)

    clear()
    print("\n".join(lines))
    print(f"\n  {datetime.now().strftime('%H:%M:%S')}")


def evaluate(expr: str) -> str:
    """Safely evaluate a math expression."""
    try:
        # Allow math functions
        safe = {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow, "sqrt": math.sqrt,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log2": math.log2, "log10": math.log10,
            "pi": math.pi, "e": math.e, "tau": math.tau,
            "inf": math.inf, "nan": math.nan,
        }
        result = eval(expr, {"__builtins__": {}}, safe)
        if isinstance(result, float):
            if result == int(result) and not math.isinf(result):
                return str(int(result))
            return f"{result:.10g}"
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def main():
    history = []
    display = ""

    print("\n  Type an expression (e.g. 2+2, sqrt(16), 3*pi)")
    print("  Functions: abs, round, min, max, pow, sqrt, sin, cos, tan, log")
    print("  Constants: pi, e, tau  |  'q' to quit\n")

    while True:
        try:
            raw = input("  >>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break

        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            print("\n  Bye!")
            break

        result = evaluate(raw)
        entry = f"  {raw} = {result}"
        history.append(entry)
        display = f"{raw} = {result}"

        render(display, history)


if __name__ == "__main__":
    main()