"""
Graphical User Interface for qforge using tkinter.

Converted from the prompt_toolkit-based interactive.py CLI.

Key fixes in this version
--------------------------
 1.  ConsoleRedirector.write() fully parses Rich markup tags AND ANSI codes.
     Box-drawing characters are left UNCHANGED so Rich tables render with
     correct Unicode glyphs (╭─┬─╮ etc.) — Consolas supports them all.
 2.  Broader ANSI SGR code support: bold (1), dim (2), italic (3), underline
     (4), colours 30-37 / 90-97 (bright) all handled.
 3.  SearchablePickerDialog: a themed Toplevel with a live-filter Entry +
     Listbox that replaces simpledialog.askstring for any selection that has
     a known choices list.  The user can also type freely and hit Enter.
 4.  All wizard _ask_string calls that have a choices list now use _ask_choice
     so the user can click-to-select or type-to-filter — no more typos.
 5.  Complete Nord dark-theme with accent sidebar, animated status dot, etc.
"""

import os
import sys
import subprocess
import threading
import runpy
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import re

# Do NOT set NO_COLOR or PLOTEXT_USE_UNICODE=0 here.
# Plotext needs to emit its full ANSI color sequences so the console
# redirector can render the golden axes, colored series lines, etc.
# Unicode block chars (▞▀▄ etc.) used by plotext are left intact.

_current_dir  = os.path.dirname(os.path.abspath(__file__))
_parent_dir   = os.path.dirname(_current_dir)
_project_root = os.path.dirname(_parent_dir)

os.chdir(_project_root)

for _p in (_current_dir, _parent_dir, _project_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --------------------------------------------------------------------------- #
#  QForge imports                                                               #
# --------------------------------------------------------------------------- #
_QFORGE_AVAILABLE = True
try:
    from qforge.cli.commands.example import list_example_files, get_examples_dir
    from qforge.core.qubit_engine import QubitEngine
    from qforge.core.gate_engine import GateEngine
    from qforge.core.workflow_engine import PhysicalWorkflowEngine
    from qforge.core.error_correction_engine import ErrorCorrectionEngine
    from qforge.config.defaults import QUBIT_PRESETS
    from qforge.cli.commands.qubit import _create_qubit, list_qubits, analyze, delete
    from qforge.cli.commands.gate import simulate
    from qforge.cli.commands.compare import compare_qubits
    from qforge.utils.terminal_plot import TerminalPlotter
except ImportError:
    _QFORGE_AVAILABLE = False
    print("Warning: qforge modules not found. Running in UI testing mode.")

    class _Stub:
        def __init__(self, *a, **kw): pass
        def __call__(self, *a, **kw): return self
        def __getattr__(self, _): return self
        def load_session(self): pass
        def list_qubits(self): return []

    QubitEngine = GateEngine = PhysicalWorkflowEngine = ErrorCorrectionEngine = _Stub
    TerminalPlotter = _Stub
    QUBIT_PRESETS = {"transmon": {"typical": {"EJ": 15.0, "EC": 0.2, "ng": 0.0, "ncut": 30}}}
    def list_example_files(): return []
    def get_examples_dir(): return "."
    def _create_qubit(*a, **kw): print("(stub) _create_qubit called")
    class _FakeCmd:
        @staticmethod
        def callback(**kw): print(f"(stub) callback called with {kw}")
    list_qubits = analyze = delete = simulate = compare_qubits = _FakeCmd()


# --------------------------------------------------------------------------- #
#  Colour / style palette                                                       #
# --------------------------------------------------------------------------- #

C = {
    "bg_dark":    "#1E2130",
    "bg_panel":   "#242938",
    "bg_console": "#1A1D2E",
    "bg_card":    "#2E3347",
    "bg_input":   "#252A3D",
    "accent":     "#88C0D0",
    "accent2":    "#5E81AC",
    "green":      "#A3BE8C",
    "yellow":     "#EBCB8B",
    "red":        "#BF616A",
    "magenta":    "#B48EAD",
    "cyan":       "#88C0D0",
    "blue":       "#81A1C1",
    "fg":         "#ECEFF4",
    "fg_dim":     "#6B7394",
    "fg_sub":     "#8892B0",
    "separator":  "#353B54",
    "orange":     "#D08770",
    "status_ok":  "#A3BE8C",
    "status_run": "#EBCB8B",
    # picker dialog
    "pick_bg":    "#1E2130",
    "pick_sel":   "#3B4A6B",
    "pick_entry": "#252A3D",
    "pick_border":"#3E4A6A",
}

# Rich markup tag → (foreground, bold, italic)
_RICH_STYLES: dict = {
    "bold cyan":    (C["cyan"],    True,  False),
    "cyan":         (C["cyan"],    False, False),
    "bold green":   (C["green"],   True,  False),
    "green":        (C["green"],   False, False),
    "dim green":    ("#5D8A50",    False, False),
    "yellow":       (C["yellow"],  False, False),
    "bold yellow":  (C["yellow"],  True,  False),
    "red":          (C["red"],     False, False),
    "bold red":     (C["red"],     True,  False),
    "dim":          (C["fg_dim"],  False, False),
    "magenta":      (C["magenta"], False, False),
    "bold magenta": (C["magenta"], True,  False),
    "bold":         (C["fg"],      True,  False),
    "italic":       (C["fg"],      False, True),
    "white":        (C["fg"],      False, False),
    "bold white":   (C["fg"],      True,  False),
    # Extra accent styles
    "orange":       (C["orange"],  False, False),
    "bold orange":  (C["orange"],  True,  False),
}

# Regex patterns
_ANSI_COLOR_RE = re.compile(r'\x1B\[([0-9;]*)m')
_RICH_TAG_RE   = re.compile(r'\[(/?)([a-zA-Z][^\[\]/]*?)\]')

# Standard ANSI 3/4-bit foreground colour codes → named Rich tag
# (used as fallback for codes that don’t need full 256-colour lookup)
_ANSI_FG = {
    "30": "dim",      "31": "red",     "32": "green",
    "33": "yellow",   "34": "blue",    "35": "magenta",
    "36": "cyan",     "37": "white",
    # bright variants
    "90": "dim",      "91": "red",     "92": "green",
    "93": "yellow",   "94": "blue",    "95": "magenta",
    "96": "cyan",     "97": "white",
}

# --------------------------------------------------------------------------- #
#  Complete ANSI-256 colour palette → hex                                      #
#  The first 16 entries use vivid xterm defaults so plotext’s dark theme        #
#  renders with its golden axes and bright series colours exactly as seen       #
#  in a real terminal.                                                           #
# --------------------------------------------------------------------------- #

def _build_ansi256_palette() -> dict:
    """Build a full 256-entry dict mapping ANSI colour index → hex string."""
    # Basic 16 — vivid xterm defaults (what a real terminal renders)
    basic16 = [
        "#1A1D2E",  # 0  black        → use console bg so spaces are invisible
        "#CC3333",  # 1  dark red
        "#33AA33",  # 2  dark green
        "#D4A017",  # 3  orange/gold  → plotext dark-theme axes/grid/title
        "#3465A4",  # 4  dark blue    → plotext series 0
        "#8B6FB0",  # 5  dark magenta
        "#06989A",  # 6  dark cyan
        "#D3D7CF",  # 7  light gray
        "#555753",  # 8  dark gray
        "#EF5350",  # 9  bright red   → plotext series 5 (red+)
        "#8AE234",  # 10 bright green → plotext series 4 (green+)
        "#FCE94F",  # 11 bright yellow
        "#729FCF",  # 12 bright blue  → plotext series 3 (blue+)
        "#C07ADB",  # 13 bright mag.  → plotext series 7 (magenta+)
        "#34E2E2",  # 14 bright cyan  → plotext series 6 (cyan+)
        "#EEEEEC",  # 15 white
    ]
    palette: dict = {i: basic16[i] for i in range(16)}

    # 216-colour cube (indices 16–231)
    for idx in range(216):
        b = idx % 6;  rem = idx // 6
        g = rem % 6;  r   = rem // 6
        def _cv(x: int) -> int:
            return 0 if x == 0 else 55 + x * 40
        palette[16 + idx] = f"#{_cv(r):02x}{_cv(g):02x}{_cv(b):02x}"

    # Greyscale ramp (indices 232–255)
    for idx in range(24):
        v = 8 + idx * 10
        palette[232 + idx] = f"#{v:02x}{v:02x}{v:02x}"

    return palette

_ANSI256 = _build_ansi256_palette()


# --------------------------------------------------------------------------- #
#  Searchable Picker Dialog                                                     #
# --------------------------------------------------------------------------- #

class SearchablePickerDialog(tk.Toplevel):
    """
    A themed modal dialog with:
      - A title label
      - A live-filter Entry (type to narrow the list)
      - A Listbox showing matching choices
      - OK / Cancel buttons
      - Returns the selected/typed value, or None if cancelled.

    The user can either click an item in the list or type freely in the entry.
    Pressing Enter confirms; Escape cancels.
    """

    def __init__(self, parent, title: str, prompt: str,
                 choices: list, default: str = ""):
        super().__init__(parent)
        self.title(title)
        self.resizable(True, False)   # allow horizontal resize if needed
        self.configure(bg=C["pick_bg"])
        self.result: str | None = None

        # Keep it modal
        self.transient(parent)
        self.grab_set()

        self._choices = choices

        # ── Compute a sensible dialog width from the longest option ─── #
        # Consolas 12 px → roughly 7.5 px per character; add 80 px padding
        # for scrollbar + list indent.  Clamp to [420, 680].
        max_item_len = max((len(c) for c in choices), default=20)
        computed_w   = max(420, min(680, max_item_len * 8 + 100))
        self._dlg_width = computed_w

        self._build_ui(prompt, default)

        # Force the width before centering so winfo_width() is correct
        list_h = min(10, max(4, len(choices)))
        approx_h = 260 + list_h * 20          # rough height estimate
        self.geometry(f"{computed_w}x{approx_h}")
        self.update_idletasks()

        # Centre over parent
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - self.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"{computed_w}x{approx_h}+{px}+{py}")

        self._entry.focus_set()
        if default:
            self._entry.delete(0, tk.END)
            self._entry.insert(0, default)
            self._entry.select_range(0, tk.END)

        self.bind("<Escape>", lambda _: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window()

    # ------------------------------------------------------------------ #

    def _build_ui(self, prompt: str, default: str):
        PAD = 16
        wrap_w = self._dlg_width - PAD * 2   # label wraps to dialog width

        # ── Prompt label ─────────────────────────────────────────────── #
        lbl = tk.Label(
            self, text=prompt,
            bg=C["pick_bg"], fg=C["accent"],
            font=("Helvetica", 11),
            justify="left", anchor="w",
            wraplength=wrap_w,
        )
        lbl.pack(fill=tk.X, padx=PAD, pady=(PAD, 8))

        # ── Filter label ─────────────────────────────────────────────── #
        tk.Label(
            self, text="🔍  Filter",
            bg=C["pick_bg"], fg=C["fg_dim"],
            font=("Helvetica", 9),
            anchor="w",
        ).pack(fill=tk.X, padx=PAD, pady=(0, 2))

        # ── Filter entry ──────────────────────────────────────────────── #
        entry_frame = tk.Frame(self, bg=C["pick_border"], padx=1, pady=1)
        entry_frame.pack(fill=tk.X, padx=PAD, pady=(0, 6))

        self._entry = tk.Entry(
            entry_frame,
            bg=C["pick_entry"], fg=C["accent"],
            insertbackground=C["accent"],
            relief="flat",
            font=("Consolas", 12),
            bd=0,
        )
        self._entry.pack(fill=tk.X, padx=6, pady=6)
        self._entry.bind("<KeyRelease>", self._on_filter)
        self._entry.bind("<Return>",     lambda _: self._ok())
        self._entry.bind("<Down>",       lambda _: self._focus_list())

        # ── Listbox ───────────────────────────────────────────────────── #
        list_frame = tk.Frame(self, bg=C["pick_border"], padx=1, pady=1)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(0, 10))

        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                          bg=C["bg_card"], troughcolor=C["pick_bg"],
                          width=10, relief="flat")
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._listbox = tk.Listbox(
            list_frame,
            bg=C["bg_console"], fg=C["fg"],
            selectbackground=C["pick_sel"], selectforeground=C["accent"],
            activestyle="none",
            font=("Consolas", 12),
            relief="flat", bd=0,
            yscrollcommand=sb.set,
            height=min(10, max(4, len(self._choices))),
            exportselection=False,
        )
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self._listbox.yview)

        self._listbox.bind("<Double-Button-1>", lambda _: self._ok())
        self._listbox.bind("<Return>",          lambda _: self._ok())
        self._listbox.bind("<Up>",              self._list_up)

        # Count label (updated on filter)
        self._count_var = tk.StringVar()
        tk.Label(
            self, textvariable=self._count_var,
            bg=C["pick_bg"], fg=C["fg_dim"],
            font=("Helvetica", 9), anchor="e",
        ).pack(fill=tk.X, padx=PAD, pady=(0, 4))

        self._populate(self._choices)

        # Pre-select the default if it's in the list
        if default in self._choices:
            idx = self._choices.index(default)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)

        # ── Buttons ───────────────────────────────────────────────────── #
        btn_row = tk.Frame(self, bg=C["pick_bg"])
        btn_row.pack(fill=tk.X, padx=PAD, pady=(0, PAD))

        tk.Button(
            btn_row, text="Cancel",
            bg=C["bg_card"], fg=C["fg_sub"],
            activebackground=C["bg_card"], activeforeground=C["fg"],
            relief="flat", font=("Helvetica", 10),
            padx=16, pady=6, cursor="hand2",
            command=self._cancel,
        ).pack(side=tk.RIGHT, padx=(6, 0))

        tk.Button(
            btn_row, text="  OK  ",
            bg=C["accent2"], fg=C["fg"],
            activebackground=C["accent"], activeforeground=C["fg"],
            relief="flat", font=("Helvetica", 10, "bold"),
            padx=16, pady=6, cursor="hand2",
            command=self._ok,
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ #

    def _populate(self, items: list, total: int = -1):
        self._listbox.delete(0, tk.END)
        for item in items:
            self._listbox.insert(tk.END, f"  {item}")
        shown = len(items)
        tot   = total if total >= 0 else shown
        if shown == tot:
            self._count_var.set(f"{tot} option{'s' if tot != 1 else ''}")
        else:
            self._count_var.set(f"{shown} of {tot} options")

    def _on_filter(self, _event=None):
        query    = self._entry.get().strip().lower()
        filtered = [c for c in self._choices if query in c.lower()] if query else self._choices
        self._populate(filtered, total=len(self._choices))
        if filtered:
            self._listbox.selection_set(0)

    def _focus_list(self):
        if self._listbox.size():
            self._listbox.focus_set()
            self._listbox.selection_set(0)

    def _list_up(self, event):
        """When Up is pressed at the top of the list, return focus to entry."""
        sel = self._listbox.curselection()
        if sel and sel[0] == 0:
            self._entry.focus_set()

    def _ok(self):
        # Prefer a clicked list item; fall back to typed text
        sel = self._listbox.curselection()
        if sel:
            raw = self._listbox.get(sel[0]).strip()
            self.result = raw
        else:
            typed = self._entry.get().strip()
            self.result = typed if typed else None
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# --------------------------------------------------------------------------- #
#  Console redirector — Rich markup + ANSI → Tkinter text tags                 #
# --------------------------------------------------------------------------- #

class ConsoleRedirector:
    """
    Redirects sys.stdout / sys.stderr to a Tkinter Text widget.

    Rendering pipeline:
      1. Split on ANSI SGR colour codes → update current colour tag.
         Supports: 3/4-bit (30-37, 90-97), 256-colour (38;5;N / 48;5;N),
         and 24-bit true-colour (38;2;R;G;B).
         Background codes (48;…) are parsed then ignored — background is
         always the console widget's own background colour.
         Dynamic Tk tags are registered on-the-fly for any colour that
         doesn't already have a named tag.
      2. Within each text chunk, tokenise Rich [tag] / [/tag] markup →
         maintain a style stack.
      3. Insert text segments with the active Tkinter tag.

    Box-drawing characters (╭╮╯╰│─├┤┬┴┼━┃ etc.) are passed through
    UNCHANGED.  Every tag uses an identical mono font so Rich table
    columns stay perfectly aligned regardless of colour.
    """

    def __init__(self, text_widget: tk.Text, root: tk.Tk):
        self.text_widget      = text_widget
        self.root             = root
        self._style_stack     = []        # stack of active Rich tag names
        self._ansi_tag        = "white"   # current ANSI foreground tag name
        self._bold            = False     # ANSI bold state (kept for 3/4-bit mapping)
        self._ansi_re         = _ANSI_COLOR_RE
        self._dynamic_tags: set = set()   # hex colour tags already registered

    # ------------------------------------------------------------------ #

    def _effective_tag(self) -> str:
        """The innermost active tag (Rich stack → ANSI fallback)."""
        if self._style_stack:
            return self._style_stack[-1]
        return self._ansi_tag

    def _ensure_hex_tag(self, hex_color: str) -> str:
        """
        Return a Tk tag name for the given hex colour string, creating the
        tag on demand so plotext colours render without pre-registration.
        All dynamic tags use the same mono font as pre-registered tags so
        table alignment is never broken.
        """
        if hex_color not in self._dynamic_tags:
            self.text_widget.tag_config(
                hex_color,
                foreground=hex_color,
                font=("Consolas", 12, "normal", "roman"),
            )
            self._dynamic_tags.add(hex_color)
        return hex_color

    def _handle_ansi_codes(self, codes: str):
        """
        Parse a semicolon-separated SGR sequence and update the current
        ANSI foreground tag.  Handles:
          0              → reset
          1              → bold flag (font stays mono; weight conveyed by colour)
          2              → dim
          30-37, 90-97   → standard 3/4-bit colours (mapped through _ANSI_FG)
          38;5;N         → 256-colour foreground  (looked up in _ANSI256)
          38;2;R;G;B     → 24-bit true-colour foreground
          48;5;N         → 256-colour background  (skip — bg not rendered)
          48;2;R;G;B     → 24-bit true-colour background (skip)
          39, 49         → default fg/bg → reset to white
        """
        parts = codes.split(";") if codes else ["0"]
        i = 0
        while i < len(parts):
            p = parts[i].strip()

            if p in ("0", ""):                   # SGR full reset
                self._ansi_tag = "white"
                self._bold     = False
                i += 1

            elif p == "1":                        # bold on
                self._bold = True
                i += 1

            elif p == "22":                       # normal intensity
                self._bold = False
                i += 1

            elif p == "2":                        # dim
                self._ansi_tag = "dim"
                i += 1

            elif p in ("39", "49"):               # default fg / bg
                if p == "39":
                    self._ansi_tag = "white"
                i += 1

            elif p == "38":                       # extended foreground
                if (i + 2 < len(parts)
                        and parts[i + 1].strip() == "5"):
                    # 38;5;N  — ANSI-256 foreground
                    try:
                        n       = int(parts[i + 2].strip())
                        hex_col = _ANSI256.get(n, "#ECEFF4")
                    except (ValueError, IndexError):
                        hex_col = "#ECEFF4"
                    self._ansi_tag = self._ensure_hex_tag(hex_col)
                    i += 3
                elif (i + 4 < len(parts)
                        and parts[i + 1].strip() == "2"):
                    # 38;2;R;G;B — true-colour foreground
                    try:
                        r = int(parts[i + 2].strip())
                        g = int(parts[i + 3].strip())
                        b = int(parts[i + 4].strip())
                        hex_col = f"#{r:02x}{g:02x}{b:02x}"
                    except (ValueError, IndexError):
                        hex_col = "#ECEFF4"
                    self._ansi_tag = self._ensure_hex_tag(hex_col)
                    i += 5
                else:
                    i += 1

            elif p == "48":                       # extended background — skip
                if i + 1 < len(parts) and parts[i + 1].strip() == "5":
                    i += 3   # 48;5;N
                elif i + 1 < len(parts) and parts[i + 1].strip() == "2":
                    i += 5   # 48;2;R;G;B
                else:
                    i += 1

            elif p in _ANSI_FG:                   # standard 3/4-bit colour
                base = _ANSI_FG[p]
                if self._bold:
                    candidate = f"bold {base}"
                    self._ansi_tag = candidate if candidate in _RICH_STYLES else base
                else:
                    self._ansi_tag = base
                i += 1

            else:
                i += 1    # unknown or unhandled code — skip

    # ------------------------------------------------------------------ #

    def write(self, raw: str):
        if not raw:
            return

        def _process():
            # Pass A — split on ANSI colour codes
            segments = self._ansi_re.split(raw)
            # After split: [text, codes, text, codes, ...]
            ansi_chunks = []   # list of (text_chunk, ansi_tag_at_that_point)
            for idx, seg in enumerate(segments):
                if idx % 2 == 1:
                    # captured SGR code group
                    self._handle_ansi_codes(seg)
                else:
                    ansi_chunks.append((seg, self._ansi_tag))

            # Pass B — parse Rich markup within each ANSI-clean chunk
            for chunk_text, ansi_tag in ansi_chunks:
                if not chunk_text:
                    continue

                pos = 0
                for m in _RICH_TAG_RE.finditer(chunk_text):
                    # Emit literal text before this tag
                    before = chunk_text[pos:m.start()]
                    if before:
                        tag = self._effective_tag() if self._style_stack else ansi_tag
                        self.text_widget.insert(tk.END, before, tag)

                    slash, tag_name = m.group(1), m.group(2).strip()

                    if not slash:
                        # Opening tag
                        if tag_name in _RICH_STYLES:
                            self._style_stack.append(tag_name)
                        # (unknown tags are silently ignored — not printed)
                    else:
                        # Closing tag — pop from stack
                        if self._style_stack and self._style_stack[-1] == tag_name:
                            self._style_stack.pop()
                        elif tag_name in self._style_stack:
                            while self._style_stack and self._style_stack[-1] != tag_name:
                                self._style_stack.pop()
                            if self._style_stack:
                                self._style_stack.pop()

                    pos = m.end()

                # Trailing text after last tag
                tail = chunk_text[pos:]
                if tail:
                    tag = self._effective_tag() if self._style_stack else ansi_tag
                    self.text_widget.insert(tk.END, tail, tag)

            self.text_widget.see(tk.END)

        self.root.after(0, _process)

    def flush(self):
        pass


# --------------------------------------------------------------------------- #
#  Main application                                                             #
# --------------------------------------------------------------------------- #

class QForgeGUI(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title("qforge  ·  Quantum Simulation Environment")
        self.geometry("1200x760")
        self.minsize(880, 520)
        self.configure(bg=C["bg_dark"])

        base_dir  = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "assets", "fav.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

        try:
            self.engine = QubitEngine()
            self.engine.load_session()
        except Exception:
            self.engine = None

        self._setup_styles()
        self._setup_ui()
        self._register_console_tags()
        self._redirect_console()
        self._print_welcome()

        self.after(120, self._set_sash)

    # ---------------------------------------------------------------------- #
    #  TTK styles                                                              #
    # ---------------------------------------------------------------------- #

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame",       background=C["bg_dark"])
        style.configure("TPanedwindow", background=C["bg_dark"])
        style.configure("TSeparator",   background=C["separator"])

        style.configure(
            "SidebarHeader.TLabel",
            font=("Helvetica", 11, "bold"),
            background=C["bg_panel"],
            foreground=C["fg_dim"],
            padding=(0, 6, 0, 4),
        )
        style.configure(
            "Nav.TButton",
            font=("Helvetica", 11),
            padding=(10, 8),
            background=C["bg_panel"],
            foreground=C["fg"],
            relief="flat",
            borderwidth=0,
            anchor="w",
        )
        style.map(
            "Nav.TButton",
            background=[("active", C["bg_card"]), ("pressed", C["accent2"])],
            foreground=[("active", C["fg"]),      ("pressed", C["fg"])],
        )
        style.configure(
            "Danger.TButton",
            font=("Helvetica", 11),
            padding=(10, 8),
            background="#3D2232",
            foreground=C["red"],
            relief="flat",
            borderwidth=0,
            anchor="w",
        )
        style.map(
            "Danger.TButton",
            background=[("active", C["red"]), ("pressed", "#8B3A42")],
            foreground=[("active", C["fg"])],
        )
        style.configure(
            "Console.Vertical.TScrollbar",
            background=C["bg_card"],
            troughcolor=C["bg_console"],
            arrowcolor=C["fg_dim"],
            borderwidth=0,
        )
        style.configure(
            "Console.Horizontal.TScrollbar",
            background=C["bg_card"],
            troughcolor=C["bg_console"],
            arrowcolor=C["fg_dim"],
            borderwidth=0,
        )

    # ---------------------------------------------------------------------- #
    #  UI construction                                                         #
    # ---------------------------------------------------------------------- #

    def _setup_ui(self):
        # ── Top bar ───────────────────────────────────────────────────── #
        top = tk.Frame(self, bg=C["bg_panel"], height=44)
        top.pack(fill=tk.X, side=tk.TOP)
        top.pack_propagate(False)

        tk.Frame(top, bg=C["accent2"], width=3).pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(
            top, text="  ⚛  qforge",
            bg=C["bg_panel"], fg=C["accent"],
            font=("Helvetica", 14, "bold"),
        ).pack(side=tk.LEFT, padx=(10, 0), pady=8)

        tk.Label(
            top, text=" — Quantum Simulation Environment",
            bg=C["bg_panel"], fg=C["fg_sub"],
            font=("Helvetica", 11),
        ).pack(side=tk.LEFT, pady=8)

        tk.Label(
            top, text="v2.0 ",
            bg=C["bg_panel"], fg=C["fg_dim"],
            font=("Helvetica", 9),
        ).pack(side=tk.RIGHT, pady=8, padx=12)

        # ── Main pane ─────────────────────────────────────────────────── #
        self.main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar ───────────────────────────────────────────────────── #
        sidebar = tk.Frame(self.main_paned, bg=C["bg_panel"], width=240)
        self.main_paned.add(sidebar, weight=0)

        inner = tk.Frame(sidebar, bg=C["bg_panel"])
        inner.pack(fill=tk.BOTH, expand=True)

        ttk.Label(inner, text="WORKFLOWS", style="SidebarHeader.TLabel").pack(
            fill=tk.X, padx=14, pady=(14, 2)
        )
        tk.Frame(inner, bg=C["accent2"], height=1).pack(fill=tk.X, padx=14, pady=(0, 6))

        button_defs = [
            ("➕   Create a qubit",           self._wizard_create_qubit),
            ("📋   List qubits",               self._wizard_list_qubits),
            ("🔬   Analyze a qubit",           self._wizard_analyze_qubit),
            ("🗑   Delete a qubit",            self._wizard_delete_qubit),
            ("⚡   Simulate gates",            self._wizard_simulate_gate),
            ("🔗   Build a circuit",           self._wizard_build_circuit),
            ("🖥   Design hardware",           self._wizard_design_hardware),
            ("⚖   Compare qubits",            self._wizard_compare_qubits),
            ("🔀   Multi-qubit gate analysis", self._wizard_analyze_multi),
            ("▶   Run an example",            self._wizard_run_example),
            ("🚀   Run full workflow",         self._wizard_full_workflow),
            ("❓   Help",                      self._show_help),
        ]

        for text, cmd in button_defs:
            ttk.Button(inner, text=text, command=cmd, style="Nav.TButton").pack(
                fill=tk.X, padx=6, pady=1
            )

        tk.Frame(inner, bg=C["bg_panel"]).pack(fill=tk.BOTH, expand=True)
        tk.Frame(inner, bg=C["separator"], height=1).pack(fill=tk.X, padx=14, pady=4)
        ttk.Button(inner, text="✕   Exit", command=self._safe_quit,
                   style="Danger.TButton").pack(fill=tk.X, padx=6, pady=(2, 10))

        # ── Console panel ─────────────────────────────────────────────── #
        console_panel = tk.Frame(self.main_paned, bg=C["bg_dark"])
        self.main_paned.add(console_panel, weight=1)

        hdr = tk.Frame(console_panel, bg=C["bg_dark"], height=28)
        hdr.pack(fill=tk.X, padx=10, pady=(8, 2))
        hdr.pack_propagate(False)

        tk.Label(
            hdr, text="Console Output",
            bg=C["bg_dark"], fg=C["fg_dim"],
            font=("Helvetica", 9, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            hdr, text="Clear", bg=C["bg_dark"], fg=C["fg_dim"],
            font=("Helvetica", 9, "underline"), cursor="hand2",
        ).pack(side=tk.RIGHT)
        hdr.winfo_children()[-1].bind("<Button-1>", lambda _: self._clear_console())

        console_outer = tk.Frame(console_panel, bg=C["bg_dark"])
        console_outer.pack(fill=tk.BOTH, expand=True, padx=10)

        self._v_scroll = ttk.Scrollbar(
            console_outer, orient=tk.VERTICAL,
            style="Console.Vertical.TScrollbar",
        )
        self._v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.console_text = tk.Text(
            console_outer,
            bg=C["bg_console"], fg=C["fg"],
            font=("Consolas", 12),
            wrap=tk.NONE,                 # no wrapping — tables/plots stay aligned
            yscrollcommand=self._v_scroll.set,
            state=tk.NORMAL,
            insertbackground=C["fg"],
            selectbackground=C["accent2"],
            selectforeground=C["fg"],
            padx=10, pady=8,
            relief="flat", borderwidth=0,
        )
        self.console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._v_scroll.config(command=self.console_text.yview)

        self._h_scroll = ttk.Scrollbar(
            console_panel, orient=tk.HORIZONTAL,
            command=self.console_text.xview,
            style="Console.Horizontal.TScrollbar",
        )
        self._h_scroll.pack(fill=tk.X, padx=10)
        self.console_text.config(xscrollcommand=self._h_scroll.set)

        # ── Status bar ────────────────────────────────────────────────── #
        status_bar = tk.Frame(self, bg=C["bg_panel"], height=26)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        tk.Frame(status_bar, bg=C["accent2"], width=3).pack(side=tk.LEFT, fill=tk.Y)

        self._status_dot = tk.Label(
            status_bar, text="●", bg=C["bg_panel"], fg=C["status_ok"],
            font=("Helvetica", 9),
        )
        self._status_dot.pack(side=tk.LEFT, padx=(8, 4))

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            status_bar, textvariable=self.status_var,
            bg=C["bg_panel"], fg=C["fg_sub"],
            font=("Helvetica", 9), anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X)

    def _set_sash(self):
        try:
            self.main_paned.sashpos(0, 240)
        except Exception:
            pass

    def _clear_console(self):
        self.console_text.delete("1.0", tk.END)

    # ---------------------------------------------------------------------- #
    #  Register Tkinter text tags                                              #
    # ---------------------------------------------------------------------- #

    def _register_console_tags(self):
        w = self.console_text
        # CRITICAL: every tag must use EXACTLY the same font tuple so that
        # character-cell widths are identical everywhere.  Bold/italic font
        # variants change glyph metrics in many renderers, which causes
        # Rich table columns to drift.  Colour differentiation is used
        # instead of weight/style variation.
        _MONO = ("Consolas", 12, "normal", "roman")

        for tag_name, (fg, _bold, _italic) in _RICH_STYLES.items():
            w.tag_config(tag_name, foreground=fg, font=_MONO)

        # Plain ANSI colour names not already covered by _RICH_STYLES
        for name, fg in {
            "red": C["red"], "green": C["green"], "yellow": C["yellow"],
            "blue": C["blue"], "magenta": C["magenta"], "cyan": C["cyan"],
            "white": C["fg"],
        }.items():
            if name not in _RICH_STYLES:
                w.tag_config(name, foreground=fg, font=_MONO)

        w.tag_config("white", foreground=C["fg"], font=_MONO)

    # ---------------------------------------------------------------------- #
    #  Console redirection                                                     #
    # ---------------------------------------------------------------------- #

    def _redirect_console(self):
        self._redirector = ConsoleRedirector(self.console_text, self)
        sys.stdout = self._redirector
        sys.stderr = self._redirector

    def _print_welcome(self):
        w = 62
        print("─" * w)
        print(f"[bold cyan]  ⚛  qforge  –  Quantum Simulation Environment[/bold cyan]")
        print("─" * w)
        print(f"[dim]  Powered by scqubits and QuTiP.[/dim]")
        print(f"[dim]  Please cite these libraries in your research.[/dim]")
        print("─" * w)
        print()
        print(f"[dim]Click a workflow button on the left to get started.[/dim]")
        print()

    # ---------------------------------------------------------------------- #
    #  Status bar                                                              #
    # ---------------------------------------------------------------------- #

    def _set_status(self, msg: str, running: bool = False):
        self.status_var.set(msg)
        self._status_dot.config(fg=C["status_run"] if running else C["status_ok"])
        self.update_idletasks()

    # ---------------------------------------------------------------------- #
    #  Dialog helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _ask_string(self, title: str, prompt_text: str, default: str = "") -> "str | None":
        """Plain text-entry dialog (no choices list)."""
        return simpledialog.askstring(
            title, prompt_text, initialvalue=default, parent=self
        )

    def _ask_choice(self, title: str, prompt_text: str,
                    choices: list, default: str = "") -> "str | None":
        """
        Searchable picker dialog.  The user can click an item or type freely.
        Returns the selected/typed value, or None if cancelled.
        """
        dlg = SearchablePickerDialog(self, title, prompt_text, choices, default)
        return dlg.result

    # ---------------------------------------------------------------------- #
    #  Engine helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _refresh_engine(self):
        try:
            self.engine = QubitEngine()
            self.engine.load_session()
        except Exception:
            pass

    def _get_qubit_names(self) -> list:
        self._refresh_engine()
        if not self.engine:
            return []
        try:
            return [q["name"] for q in self.engine.list_qubits()]
        except Exception:
            return []

    def _run_in_thread(self, fn, *args, done_msg="Done.", **kwargs):
        self._set_status("Running…", running=True)

        def _wrap():
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                print(f"\n[red]Error: {exc}[/red]")
            finally:
                self.after(0, self._set_status, done_msg, False)

        threading.Thread(target=_wrap, daemon=True).start()

    def _safe_quit(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        self.destroy()

    # ---------------------------------------------------------------------- #
    #  Coloured print helpers                                                  #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _header(title: str):
        w = 62
        print(f"\n[bold cyan]{'─' * w}[/bold cyan]")
        print(f"[bold cyan]  {title}[/bold cyan]")
        print(f"[bold cyan]{'─' * w}[/bold cyan]")

    @staticmethod
    def _ok(msg: str):
        print(f"[bold green]  ✓  {msg}[/bold green]")

    @staticmethod
    def _warn(msg: str):
        print(f"[yellow]  ⚠  {msg}[/yellow]")

    @staticmethod
    def _err(msg: str):
        print(f"[red]  ✗  {msg}[/red]")

    @staticmethod
    def _dim(msg: str):
        print(f"[dim]{msg}[/dim]")

    @staticmethod
    def _cprint(text: str):
        print(text)

    # ---------------------------------------------------------------------- #
    #  Wizard: Create a qubit                                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_create_qubit(self):
        self._header("Qubit Creation Wizard")

        if not _QFORGE_AVAILABLE:
            self._err("(stub mode) qforge not installed.")
            return

        qubit_types = list(QUBIT_PRESETS.keys())
        q_type = self._ask_choice(
            "Qubit Type",
            "Select qubit type:",
            qubit_types,
        )
        if not q_type:
            self._warn("Aborted.")
            return
        q_type = q_type.strip().lower()
        if q_type not in qubit_types:
            self._err(f"Unknown qubit type: '{q_type}'. Aborted.")
            return

        name = self._ask_string("Qubit Name", "Enter a name for your qubit:")
        if not name:
            self._warn("Aborted.")
            return
        name = name.strip()

        defaults = QUBIT_PRESETS[q_type].get("typical", {})
        params = {}

        self._cprint(f"\n[yellow]Configuring [bold]{q_type}[/bold] "
                     f"(press OK with empty input to accept default):[/yellow]")

        for key, default_val in defaults.items():
            val_str = self._ask_string(
                f"Parameter: {key}",
                f"{key}  [default: {default_val}]:",
                str(default_val),
            )
            if val_str is None:
                self._warn("Aborted.")
                return

            val_str = val_str.strip()
            if not val_str:
                params[key] = default_val
            else:
                try:
                    if isinstance(default_val, int):
                        params[key] = int(val_str)
                    elif isinstance(default_val, float):
                        params[key] = float(val_str)
                    else:
                        params[key] = val_str
                except ValueError:
                    self._err(f"Invalid input for '{key}', using default ({default_val}).")
                    params[key] = default_val

        cmd_hint = f"qforge qubit create {q_type} --name {name}"
        for k, v in params.items():
            cmd_hint += f" --{k} {v}"
        self._dim(f"Equivalent command: {cmd_hint}")

        self._cprint(f"\n[green]Creating {q_type} '[bold]{name}[/bold]'…[/green]")

        def _do():
            try:
                _create_qubit(q_type, name, params)
                self._ok(f"Qubit '{name}' created successfully!")
                self.after(0, messagebox.showinfo, "Success",
                           f"Qubit '{name}' created successfully!")
            except Exception as e:
                self._err(f"Error: {e}")

        self._run_in_thread(_do, done_msg="Create complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: List qubits                                                     #
    # ---------------------------------------------------------------------- #

    def _wizard_list_qubits(self):
        self._header("Qubit Inventory")
        self._refresh_engine()
        try:
            qubits = self.engine.list_qubits()
        except Exception:
            qubits = []

        if not qubits:
            self._warn("No qubits in the current session.")
            return

        col_name   = 20
        col_type   = 16
        col_freq   = 14
        col_anharm = 14
        total = col_name + col_type + col_freq + col_anharm + 9

        hdr = (f"  {'Name':<{col_name}} │ {'Type':<{col_type}} │ "
               f"{'Freq (GHz)':>{col_freq}} │ {'Anharm (MHz)':>{col_anharm}}")
        sep = "  " + "─" * total

        print(f"[bold]{hdr}[/bold]")
        print(f"[dim]{sep}[/dim]")

        for q in qubits:
            n  = str(q.get("name", "N/A"))
            t  = str(q.get("type", "N/A"))
            fr = q.get("frequency",     0.0)
            an = q.get("anharmonicity", 0.0)
            freq_str   = f"{fr:.4f}"        if isinstance(fr, float) else str(fr)
            anharm_str = f"{an * 1000:.1f}" if isinstance(an, float) else str(an)
            print(f"  [cyan]{n:<{col_name}}[/cyan] │ "
                  f"[yellow]{t:<{col_type}}[/yellow] │ "
                  f"[orange]{freq_str:>{col_freq}}[/orange] │ "
                  f"[magenta]{anharm_str:>{col_anharm}}[/magenta]")

        print(f"[dim]{sep}[/dim]")
        print(f"[dim]  {len(qubits)} qubit(s) loaded.[/dim]")

    # ---------------------------------------------------------------------- #
    #  Wizard: Analyze a qubit                                                 #
    # ---------------------------------------------------------------------- #

    def _wizard_analyze_qubit(self):
        self._header("Qubit Analysis Wizard")
        qubits = self._get_qubit_names()
        if not qubits:
            messagebox.showwarning("No Qubits", "No qubits found. Create one first.")
            return

        name = self._ask_choice(
            "Analyze Qubit", "Select qubit to analyze:", qubits
        )
        if not name:
            self._warn("Aborted.")
            return
        name = name.strip()

        do_plot = messagebox.askyesno(
            "Plot", "Generate plots?\n(Default: Yes)", default=messagebox.YES
        )
        do_coherence = messagebox.askyesno(
            "Coherence", "Estimate coherence?\n(Default: Yes)", default=messagebox.YES
        )
        do_relative = messagebox.askyesno(
            "Relative Energy", "Display relative energies?\n(Default: No)",
            default=messagebox.NO,
        )

        self._cprint(f"\n[green]Analyzing qubit: [bold]{name}[/bold][/green]")

        def _do():
            try:
                analyze.callback(
                    name=name, plot=do_plot,
                    coherence=do_coherence, relative=do_relative,
                )
            except Exception as e:
                if "Abort" not in str(type(e)):
                    self._err(f"Error: {e}")

        self._run_in_thread(_do, done_msg="Analysis complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Delete a qubit                                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_delete_qubit(self):
        self._header("Qubit Deletion Wizard")
        qubits = self._get_qubit_names()
        if not qubits:
            messagebox.showwarning("No Qubits", "No qubits to delete.")
            return

        name = self._ask_choice(
            "Delete Qubit", "Select qubit to delete:", qubits
        )
        if not name:
            self._warn("Aborted.")
            return
        name = name.strip()

        if not messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete '{name}'?\nThis cannot be undone.",
        ):
            self._dim("Deletion cancelled.")
            return

        def _do():
            try:
                delete.callback(name=name)
                g_eng = GateEngine()
                keys_to_remove = [
                    k for k in GateEngine._calib_cache.keys()
                    if k[0] == name or k[1] == name
                ]
                if keys_to_remove:
                    for key in keys_to_remove:
                        del GateEngine._calib_cache[key]
                    g_eng._save_cache_to_disk()
                    self._dim(f"  Cleared {len(keys_to_remove)} cached calibration(s) "
                              f"involving '{name}'.")
                self._ok(f"Qubit '{name}' deleted.")
                self.after(0, messagebox.showinfo, "Deleted", f"'{name}' has been deleted.")
            except Exception as e:
                if "Abort" not in str(type(e)):
                    self._err(f"Error: {e}")

        self._run_in_thread(_do, done_msg="Delete complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Simulate gates                                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_simulate_gate(self):
        self._header("Gate Simulation Wizard")
        qubits = self._get_qubit_names()
        if not qubits:
            messagebox.showwarning("No Qubits", "No qubits found. Create one first.")
            return

        qubit = self._ask_choice(
            "Select Control Qubit",
            "Select qubit (Control for 2-qubit gate):",
            qubits,
        )
        if not qubit:
            self._warn("Aborted.")
            return
        qubit = qubit.strip()

        gate_choices = ["X", "Y", "Z", "H", "CNOT", "CZ"]
        gate = self._ask_choice("Select Gate", "Select gate:", gate_choices)
        if not gate:
            self._warn("Aborted.")
            return
        gate = gate.strip().upper()

        # ── Two-qubit gate ─────────────────────────────────────────────── #
        if gate in ("CNOT", "CZ"):
            remaining = [q for q in qubits if q != qubit]
            if not remaining:
                messagebox.showwarning(
                    "Need More Qubits",
                    "You need at least two qubits for a two-qubit gate.",
                )
                return

            qubit2 = self._ask_choice(
                "Select Target Qubit",
                "Select target qubit:",
                remaining,
            )
            if not qubit2:
                self._warn("Aborted.")
                return
            qubit2 = qubit2.strip()

            duration_str = self._ask_string("Duration", "Gate duration (ns):", "50.0")
            if duration_str is None:
                self._warn("Aborted.")
                return

            c_type = self._ask_choice(
                "Coupling Type",
                "Select coupling type:",
                ["capacitive", "inductive", "tunable_coupler"],
                "tunable_coupler",
            )
            if c_type is None:
                self._warn("Aborted.")
                return
            c_type = c_type.strip() or "tunable_coupler"

            g_val_str = self._ask_string("Coupling Strength", "Coupling strength (GHz):", "0.05")
            if g_val_str is None:
                self._warn("Aborted.")
                return

            try:
                duration = float(duration_str.strip() or "50.0")
                g_val    = float(g_val_str.strip()    or "0.05")
            except ValueError:
                self._err("Invalid numeric input. Using defaults (50.0 ns, 0.05 GHz).")
                duration, g_val = 50.0, 0.05

            self._cprint(
                f"\n[green]Simulating [bold]{gate}[/bold] on "
                f"[cyan]{qubit}[/cyan] → [cyan]{qubit2}[/cyan]  "
                f"[dim]({c_type}, g = {g_val} GHz, T = {duration} ns)[/dim][/green]"
            )

            def _do_2q():
                try:
                    ge  = GateEngine()
                    res = ge.simulate_two_qubit_dynamics(
                        qubit, qubit2, gate,
                        coupling_type=c_type,
                        coupling_strength=g_val,
                        duration=duration,
                        steps=100,
                    )
                    times = res["times"]
                    pops  = res["populations"]

                    print(f"\n[bold]Final Populations:[/bold]")
                    for state, p_arr in pops.items():
                        bar = "█" * int(p_arr[-1] * 20) + "░" * (20 - int(p_arr[-1] * 20))
                        print(f"  [cyan]|{state}⟩[/cyan]  {bar}  [orange]{p_arr[-1]:.4f}[/orange]")

                    try:
                        data   = [pops[k] for k in ("00", "01", "10", "11") if k in pops]
                        labels = [f"|{k}⟩" for k in ("00", "01", "10", "11") if k in pops]
                        TerminalPlotter.plot_time_evolution(
                            times=times, expectations=data,
                            labels=labels, title=f"{gate} Dynamics", height=25,
                        )
                    except Exception as pe:
                        self._dim(f"(Plot unavailable: {pe})")

                except Exception as e:
                    self._err(f"Simulation error: {e}")

            self._run_in_thread(_do_2q, done_msg="2Q simulation complete.")

        # ── Single-qubit gate ──────────────────────────────────────────── #
        else:
            duration_str = self._ask_string("Duration", "Gate duration (ns):", "20.0")
            if duration_str is None:
                self._warn("Aborted.")
                return

            noise = self._ask_choice(
                "Noise Model", "Select noise model:",
                ["none", "realistic"], "none",
            )
            if noise is None:
                self._warn("Aborted.")
                return
            noise = noise.strip() or "none"

            try:
                duration = float(duration_str.strip() or "20.0")
            except ValueError:
                self._err("Invalid duration. Using 20.0 ns.")
                duration = 20.0

            self._cprint(
                f"\n[green]Simulating [bold]{gate}[/bold] on [cyan]{qubit}[/cyan]…[/green]"
            )

            def _do_1q():
                try:
                    simulate.callback(
                        qubit=qubit, gate=gate,
                        duration=duration, noise=noise,
                        save=False, steps=100,
                    )
                    do_save = messagebox.askyesno("Save Plot", "Save high-resolution plot to file?")
                    if do_save:
                        self._dim("Re-running to save high-res plot…")
                        simulate.callback(
                            qubit=qubit, gate=gate,
                            duration=duration, noise=noise,
                            save=True, steps=100,
                        )
                except Exception as e:
                    if "Abort" not in str(type(e)):
                        self._err(f"Error: {e}")

            self._run_in_thread(_do_1q, done_msg="1Q simulation complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Build a circuit (placeholder)                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_build_circuit(self):
        self._header("Circuit Builder")
        self._warn("Coming soon!  Command-line equivalent: qforge circuit build --help")

    # ---------------------------------------------------------------------- #
    #  Wizard: Design hardware (placeholder)                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_design_hardware(self):
        self._header("Hardware Design")
        self._warn("Coming soon!  Command-line equivalent: qforge hardware design --help")

    # ---------------------------------------------------------------------- #
    #  Wizard: Compare qubits                                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_compare_qubits(self):
        self._header("Qubit Comparison Wizard")
        qubits = self._get_qubit_names()
        if not qubits:
            messagebox.showwarning("No Qubits", "No qubits to compare.")
            return

        # Multi-select: user picks from the picker; they can type comma-separated too
        q_str = self._ask_choice(
            "Compare Qubits",
            "Select a qubit to add (or type comma-separated names):",
            qubits,
        )
        if not q_str:
            self._warn("Aborted.")
            return

        metrics = self._ask_choice(
            "Metrics",
            "Select metrics to compare:",
            ["all", "frequency", "anharmonicity", "t1", "t2"],
            "all",
        )
        if metrics is None:
            self._warn("Aborted.")
            return
        metrics = metrics.strip() or "all"

        def _do():
            try:
                compare_qubits.callback(
                    qubits=q_str.strip(), metrics=metrics,
                    gates=None, tag=None, output=None,
                )
            except Exception as e:
                if "Abort" not in str(type(e)):
                    self._err(f"Error: {e}")

        self._run_in_thread(_do, done_msg="Comparison complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Analyze multi-qubit gates                                       #
    # ---------------------------------------------------------------------- #

    def _wizard_analyze_multi(self):
        self._header("Multi-Qubit Gate Analysis Wizard")
        qubits = self._get_qubit_names()

        if len(qubits) < 2:
            messagebox.showwarning(
                "Need More Qubits",
                "You need at least two qubits for multi-qubit gate analysis.",
            )
            return

        q1 = self._ask_choice("Control Qubit", "Select Control Qubit:", qubits)
        if not q1:
            self._warn("Aborted.")
            return
        q1 = q1.strip()

        remaining = [q for q in qubits if q != q1]
        q2 = self._ask_choice("Target Qubit", "Select Target Qubit:", remaining)
        if not q2:
            self._warn("Aborted.")
            return
        q2 = q2.strip()

        gate = self._ask_choice("Gate", "Select Gate to compare:", ["CNOT", "CZ"])
        if not gate:
            self._warn("Aborted.")
            return
        gate = gate.strip().upper()

        do_tomo = messagebox.askyesno(
            "State Tomography", "Perform State Tomography (fidelity check)?",
            default=messagebox.NO,
        )

        self._cprint(
            f"\n[green]Running coupling comparison for "
            f"[bold]{gate}[/bold] on [cyan]{q1}[/cyan] → [cyan]{q2}[/cyan]…[/green]"
        )

        def _do():
            try:
                gate_engine = GateEngine()
                results = gate_engine.compare_couplings(q1, q2, gate=gate)

                col_c  = 22
                col_p  = 14
                col_ph = 12
                hdr = f"\n  [bold]{'Coupling':<{col_c}}  {'Target Pop':>{col_p}}"
                if gate == "CZ":
                    hdr += f"  {'Phase (π)':>{col_ph}}"
                if do_tomo:
                    hdr += f"  {'Fidelity':>10}"
                hdr += "[/bold]"
                print(hdr)

                sep_len = col_c + col_p + (col_ph + 2 if gate == "CZ" else 0) + (12 if do_tomo else 0) + 4
                print(f"[dim]  {'─' * sep_len}[/dim]")

                for coupling, metrics in results.items():
                    pop   = metrics.get("population", 0.0)
                    phase = metrics.get("phase", None)
                    row   = f"  [cyan]{coupling:<{col_c}}[/cyan]  [orange]{pop:>{col_p}.4f}[/orange]"
                    if gate == "CZ":
                        ph_str = f"{phase:.4f}π" if phase is not None else "N/A"
                        row += f"  [magenta]{ph_str:>{col_ph}}[/magenta]"
                    if do_tomo:
                        row += f"  [dim]{'See logs':>10}[/dim]"
                    print(row)

                print(f"[dim]  {'─' * sep_len}[/dim]")

                if gate == "CNOT":
                    self._dim("  Note: 'Target Pop' = P(|11⟩) — bit-flip success proxy.")
                elif gate == "CZ":
                    self._dim("  Note: 'Target Pop' = P(|11⟩) — population retention / leakage proxy.")

                if do_tomo:
                    self._dim("  [Detailed tomography — future integration point]")

            except Exception as e:
                self._err(f"Error during analysis: {e}")

        self._run_in_thread(_do, done_msg="Multi-qubit analysis complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Run an example                                                  #
    # ---------------------------------------------------------------------- #

    def _wizard_run_example(self):
        self._header("Run Example Wizard")
        try:
            examples = list_example_files()
        except Exception as e:
            self._err(f"Could not list examples: {e}")
            return

        if not examples:
            self._warn("No examples found.")
            return

        print(f"\n[bold]Available examples:[/bold]")
        for ex in examples:
            print(f"  [dim]·[/dim] [cyan]{ex}[/cyan]")

        ex_name = self._ask_choice("Run Example", "Select example to run:", examples)
        if not ex_name:
            self._warn("Aborted.")
            return
        ex_name = ex_name.strip()
        if not ex_name.endswith(".py"):
            ex_name += ".py"

        script_path = os.path.join(get_examples_dir(), ex_name)
        if not os.path.exists(script_path):
            messagebox.showerror("Not Found", f"Example '{ex_name}' not found.")
            self._err(f"Example '{ex_name}' not found.")
            return

        self._cprint(f"\n[green]Running [bold]{ex_name}[/bold]…[/green]")

        def _do():
            try:
                # Run the script in-process so all print() / plotext output
                # flows through ConsoleRedirector into the GUI console.
                # runpy.run_path executes the file in an isolated namespace
                # with __name__ == '__main__', identical to running it directly.
                runpy.run_path(script_path, run_name="__main__")
                self._ok(f"{ex_name} finished.")
            except SystemExit as e:
                # Scripts that call sys.exit(0) are fine; non-zero is an error
                if e.code not in (None, 0):
                    self._err(f"Example exited with code {e.code}.")
                else:
                    self._ok(f"{ex_name} finished.")
            except Exception:
                self._err(f"Error running example:")
                print(traceback.format_exc())

        self._run_in_thread(_do, done_msg="Example run complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Full workflow                                                   #
    # ---------------------------------------------------------------------- #

    def _wizard_full_workflow(self):
        self._header("Full Workflow Wizard")
        print("[dim]  Translating abstract OpenQASM circuits to superconducting physical schedules.[/dim]\n")

        available_qubits = self._get_qubit_names()
        if not available_qubits:
            messagebox.showwarning("No Qubits", "No qubits exist. Create qubits first.")
            return

        # Qubit selection — picker for each qubit slot; user decides when to stop
        print(f"[bold]1. Select Qubits[/bold]")
        qubit_names = []
        while True:
            remaining = [q for q in available_qubits if q not in qubit_names]
            if not remaining:
                break
            prompt_txt = (
                f"{'Currently selected: ' + ', '.join(qubit_names) if qubit_names else 'No qubits selected yet.'}\n\n"
                "Pick a qubit to add (Cancel when done):"
            )
            picked = self._ask_choice("Add Qubit", prompt_txt, remaining)
            if not picked:
                break
            qubit_names.append(picked.strip())
            print(f"  [green]Added:[/green] [cyan]{picked.strip()}[/cyan]")

        if not qubit_names:
            self._warn("No qubits selected. Aborted.")
            return

        # Coupling topology
        print(f"\n[bold]2. Define Native Coupling Topology[/bold]")
        print(f"[dim]   Couplings are bidirectional — specify each Q1→Q2 edge only once.[/dim]")
        couplings = []

        c_type_choices    = ["capacitive", "inductive", "tunable_coupler"]

        while messagebox.askyesno(
            "2. Add Coupling Edge",
            f"Qubits: {', '.join(qubit_names)}\n\nAdd a native coupling edge?",
        ):
            q1_input = self._ask_choice(
                "Coupling – Q1",
                "Select Q1 (first qubit in edge):",
                qubit_names,
            )
            if not q1_input:
                break
            q1_input = q1_input.strip()

            q2_choices = [q for q in qubit_names if q != q1_input]
            q2_input = self._ask_choice(
                "Coupling – Q2",
                f"Select Q2 (second qubit, paired with {q1_input}):",
                q2_choices,
            )
            if not q2_input:
                break
            q2_input = q2_input.strip()

            if q1_input not in qubit_names or q2_input not in qubit_names:
                messagebox.showerror("Invalid", f"'{q1_input}' or '{q2_input}' not in selected list.")
                continue

            ctype = self._ask_choice(
                "Coupling Type", "Select coupling type:",
                c_type_choices, "tunable_coupler",
            )
            if ctype is None:
                break
            ctype = ctype.strip() or "tunable_coupler"

            cstren_str = self._ask_string("Coupling Strength", "Strength (GHz):", "0.05")
            if cstren_str is None:
                break
            try:
                cstren = float(cstren_str.strip() or "0.05")
            except ValueError:
                self._err("Invalid strength; using 0.05 GHz.")
                cstren = 0.05

            couplings.append({
                "q1": qubit_names.index(q1_input),
                "q2": qubit_names.index(q2_input),
                "type": ctype,
                "strength": cstren,
            })
            print(f"  [green]Added[/green] [cyan]{ctype}[/cyan] "
                  f"({cstren} GHz): [cyan]{q1_input}[/cyan] ↔ [cyan]{q2_input}[/cyan]")

        use_ec = messagebox.askyesno(
            "3. Error Correction",
            "Use Quantum Error Correction?\n(3-qubit repetition code)",
            default=messagebox.NO,
        )

        qasm_path = filedialog.askopenfilename(
            title="Select OpenQASM (.qasm) File",
            filetypes=[("QASM files", "*.qasm"), ("All files", "*.*")],
            parent=self,
        )
        if not qasm_path:
            qasm_path = self._ask_string("QASM File Path", "Enter the full path to the .qasm file:")
            if not qasm_path:
                self._warn("Aborted.")
                return
            qasm_path = qasm_path.strip().strip("\"'")

        if not os.path.exists(qasm_path):
            messagebox.showerror("File Not Found", f"QASM file not found:\n{qasm_path}")
            self._err(f"QASM file '{qasm_path}' not found.")
            return

        print(f"\n[dim]Initializing workflow engines…[/dim]")

        def _do():
            try:
                g_eng = GateEngine()
                if use_ec:
                    print("[cyan]Using ErrorCorrectionEngine (3-qubit repetition code)…[/cyan]")
                    ec_eng = ErrorCorrectionEngine(self.engine, g_eng)
                    res    = ec_eng.execute_3q_repetition_workflow(qubit_names, qasm_path)
                    logical_results = res["logical_populations"]
                    print("\n[bold green]Workflow Complete![/bold green]  "
                          "[dim]Decoded Logical Populations:[/dim]")
                    for l_state, prob in sorted(logical_results.items(), key=lambda x: -x[1]):
                        if prob > 0.001:
                            print(f"  [cyan]|{l_state}⟩_L[/cyan]  [orange]{prob * 100:5.2f}%[/orange]")
                    self._dim("\nNote: Timeline plotting is disabled during active error correction.")
                else:
                    print("[cyan]Using PhysicalWorkflowEngine…[/cyan]")
                    wf_eng = PhysicalWorkflowEngine(self.engine, g_eng)
                    res    = wf_eng.execute_workflow(qubit_names, couplings, qasm_path)
                    print("\n[bold green]Simulation Complete![/bold green]  "
                          "[dim]Physical Populations:[/dim]")
                    final_pops  = {k: v[-1] for k, v in res["populations"].items()}
                    sorted_pops = sorted(final_pops.items(), key=lambda x: -x[1])
                    for state, p in sorted_pops[:8]:
                        if p > 0.01:
                            bar = "█" * int(p * 20) + "░" * (20 - int(p * 20))
                            print(f"  [cyan]|{state}⟩[/cyan]  {bar}  [orange]{p * 100:5.2f}%[/orange]")
                    top_keys = [k for k, _ in sorted_pops[:4]]
                    try:
                        plot_data = [res["populations"][k] for k in top_keys]
                        labels    = [f"P(|{k}⟩)" for k in top_keys]
                        print("\n[bold]Visual Hardware Timeline:[/bold]")
                        TerminalPlotter.plot_time_evolution(
                            times=res["times"], expectations=plot_data,
                            labels=labels,
                            title="Physical Workflow Hardware Execution Timeline",
                            height=25,
                        )
                    except Exception as pe:
                        self._dim(f"(Timeline plot unavailable: {pe})")
            except Exception as e:
                self._err(f"Workflow execution failed: {e}")
                import traceback
                traceback.print_exc()

        self._run_in_thread(_do, done_msg="Workflow complete.")

    # ---------------------------------------------------------------------- #
    #  Help                                                                    #
    # ---------------------------------------------------------------------- #

    def _show_help(self):
        self._header("qforge Help")
        print("""
[bold]Navigation[/bold]
  [dim]·[/dim] Click a button on the left panel to launch a guided wizard.
  [dim]·[/dim] Follow the dialog boxes to supply parameters.
  [dim]·[/dim] All output, errors, and plots appear in this console.
  [dim]·[/dim] Use the [cyan]Clear[/cyan] link (top-right of console) to reset output.

[bold]Workflow Reference[/bold]
  [cyan] 1.[/cyan] [green]Create a Qubit[/green]       — Define physical parameters of a superconducting qubit.
  [cyan] 2.[/cyan] [green]List Qubits[/green]           — View all saved qubits in the current session.
  [cyan] 3.[/cyan] [green]Analyze a Qubit[/green]       — Energy spectrum, coherence estimates, and plots.
  [cyan] 4.[/cyan] [green]Delete a Qubit[/green]        — Remove a qubit and clear its calibration cache.
  [cyan] 5.[/cyan] [green]Simulate Gates[/green]        — Model 1Q (X/Y/Z/H) or 2Q (CNOT/CZ) gate dynamics.
  [cyan] 6.[/cyan] [green]Build a Circuit[/green]       — [dim](Coming soon)[/dim] Construct and simulate quantum circuits.
  [cyan] 7.[/cyan] [green]Design Hardware[/green]       — [dim](Coming soon)[/dim] Layout quantum chip geometry.
  [cyan] 8.[/cyan] [green]Compare Qubits[/green]        — Side-by-side analysis of different qubit architectures.
  [cyan] 9.[/cyan] [green]Multi-Qubit Gates[/green]     — Compare coupling strategies for 2-qubit gates.
  [cyan]10.[/cyan] [green]Run an Example[/green]        — Run a bundled example script.
  [cyan]11.[/cyan] [green]Run Full Workflow[/green]     — End-to-end: QASM → physical schedule → populations.

[bold]Tips[/bold]
  [dim]·[/dim] Start with [cyan]Create a Qubit[/cyan] if you are new.
  [dim]·[/dim] Accept default parameter values for quick sanity-check runs.
  [dim]·[/dim] For command-line reference: [cyan]qforge --help[/cyan]
""")


# --------------------------------------------------------------------------- #
#  Entry point                                                                 #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app = QForgeGUI()
    app.protocol("WM_DELETE_WINDOW", app._safe_quit)
    app.mainloop()
