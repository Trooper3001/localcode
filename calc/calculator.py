"""A pretty desktop calculator built with tkinter."""

import tkinter as tk
from tkinter import font


class Calculator:
    """A clean, modern-looking calculator GUI."""

    # Color palette (dark theme)
    BG = "#1e1e2e"
    DISPLAY_BG = "#181825"
    DISPLAY_FG = "#cdd6f4"
    BTN_BG = "#313244"
    BTN_FG = "#cdd6f4"
    BTN_HOVER = "#45475a"
    OP_BG = "#89b4fa"
    OP_FG = "#1e1e2e"
    EQUAL_BG = "#a6e3a1"
    EQUAL_FG = "#1e1e2e"
    CLEAR_BG = "#f38ba8"
    CLEAR_FG = "#1e1e2e"
    ACCENT = "#cba6f7"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Calc")
        self.root.resizable(True, True)
        self.root.configure(bg=self.BG)

        # Expression and display values
        self.expression = ""
        self.result = ""

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def _build_ui(self):
        # --- Display ---
        display_frame = tk.Frame(self.root, bg=self.DISPLAY_BG, padx=12, pady=12)
        display_frame.pack(fill="x", padx=10, pady=(10, 4))

        self.expr_label = tk.Label(
            display_frame, text="", bg=self.DISPLAY_BG, fg="#6c7086",
            font=("JetBrains Mono", 11), anchor="e",
        )
        self.expr_label.pack(fill="x")

        self.display = tk.Label(
            display_frame, text="0", bg=self.DISPLAY_BG, fg=self.DISPLAY_FG,
            font=("JetBrains Mono", 28, "bold"), anchor="e",
        )
        self.display.pack(fill="x")

        # --- Button grid ---
        btn_frame = tk.Frame(self.root, bg=self.BG)
        btn_frame.pack(fill="both", expand=True, padx=10, pady=6)

        buttons = [
            ("C",  "clear",    "clear"),
            ("⌫",  "backspace", "clear"),
            ("(",  "num",      "num"),
            (")",  "num",      "num"),
            ("7",  "num",      "num"),
            ("8",  "num",      "num"),
            ("9",  "num",      "num"),
            ("÷",  "op",       "op"),
            ("4",  "num",      "num"),
            ("5",  "num",      "num"),
            ("6",  "num",      "num"),
            ("×",  "op",       "op"),
            ("1",  "num",      "num"),
            ("2",  "num",      "num"),
            ("3",  "num",      "num"),
            ("−",  "op",       "op"),
            ("0",  "num",      "num"),
            (".",  "num",      "num"),
            ("+",  "op",       "op"),
            ("=",  "equal",    "equal"),
        ]

        self.buttons = []
        for i, (label, kind, style) in enumerate(buttons):
            row, col = divmod(i, 4)
            bg, fg = self._style_colors(style)
            btn = tk.Button(
                btn_frame, text=label, bg=bg, fg=fg,
                font=("JetBrains Mono", 16, "bold"),
                bd=0, cursor="hand2",
                activebackground=self.BTN_HOVER, activeforeground=fg,
                command=lambda l=label, k=kind: self._on_button(l, k),
            )
            btn.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=self.BTN_HOVER))
            btn.bind("<Leave>", lambda e, b=btn, o=bg: b.config(bg=o))
            self.buttons.append(btn)

        for c in range(4):
            btn_frame.grid_columnconfigure(c, weight=1)
        for r in range(5):
            btn_frame.grid_rowconfigure(r, weight=1)

        # Minimum size
        self.root.minsize(280, 380)

        # Scale fonts on resize
        self.root.bind("<Configure>", self._on_resize)
        self._last_size = (0, 0)

        # Keyboard support
        self.root.bind("<Key>", self._on_key)
        self.root.focus_set()

    def _on_resize(self, event):
        if event.widget != self.root:
            return
        w, h = event.width, event.height
        if w == self._last_size[0] and h == self._last_size[1]:
            return
        self._last_size = (w, h)
        # Scale display font based on window width
        display_size = max(18, min(48, w // 10))
        self.display.config(font=("JetBrains Mono", display_size, "bold"))
        expr_size = max(9, min(16, w // 25))
        self.expr_label.config(font=("JetBrains Mono", expr_size))
        # Scale button fonts
        btn_size = max(12, min(28, w // 18))
        for btn in self.buttons:
            btn.config(font=("JetBrains Mono", btn_size, "bold"))

    def _style_colors(self, style):
        if style == "op":
            return self.OP_BG, self.OP_FG
        if style == "equal":
            return self.EQUAL_BG, self.EQUAL_FG
        if style == "clear":
            return self.CLEAR_BG, self.CLEAR_FG
        return self.BTN_BG, self.BTN_FG

    def _on_button(self, label, kind):
        if kind == "num":
            self.expression += label
        elif kind == "op":
            op_map = {"÷": "/", "×": "*", "−": "-"}
            self.expression += op_map.get(label, label)
        elif kind == "clear":
            self.expression = ""
            self.result = ""
        elif kind == "backspace":
            self.expression = self.expression[:-1]
        elif kind == "equal":
            self._evaluate()
        self._update_display()

    def _on_key(self, event):
        key = event.char
        if key.isdigit() or key in "().+-*/":
            self.expression += key
        elif key == "\r":  # Enter
            self._evaluate()
        elif event.keysym == "BackSpace":
            self.expression = self.expression[:-1]
        elif event.keysym == "Escape":
            self.expression = ""
            self.result = ""
        else:
            return
        self._update_display()

    def _evaluate(self):
        try:
            # Only allow safe math
            safe = self.expression.replace(" ", "")
            if not safe:
                return
            val = eval(safe, {"__builtins__": {}}, {})
            # Format: strip trailing zeros
            if isinstance(val, float):
                val = f"{val:.10f}".rstrip("0").rstrip(".")
            self.result = str(val)
        except Exception:
            self.result = "Error"

    def _update_display(self):
        # Show expression (pretty symbols)
        pretty = self.expression.replace("/", "÷").replace("*", "×").replace("-", "−")
        self.expr_label.config(text=pretty)
        # Show result or current input
        if self.result:
            self.display.config(text=self.result)
        else:
            self.display.config(text=self.expression or "0")

    def run(self):
        self.root.mainloop()


def main():
    Calculator().run()


if __name__ == "__main__":
    main()
