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
import threading
import runpy
import traceback
import webbrowser
import tkinter as tk
from tkinter import ttk, simpledialog, filedialog
import re

DOCS_URL = "https://qforge.readthedocs.io/en/latest/"

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
    from qforge import __version__
    from qforge.cli.commands.example import list_example_files, get_examples_dir
    from qforge.core.qubit_engine import QubitEngine
    from qforge.core.gate_engine import GateEngine
    from qforge.core.workflow_engine import PhysicalWorkflowEngine
    from qforge.core.error_correction_engine import ErrorCorrectionEngine
    from qforge.core.stabilizer_codes import REPETITION_3, STEANE_7, SHOR_9
    from qforge.config.defaults import QUBIT_PRESETS, OUTPUT_DIRS
    from qforge.cli.commands.qubit import _create_qubit, list_qubits, analyze, delete
    from qforge.cli.commands.gate import simulate
    from qforge.cli.commands.compare import compare_qubits
    from qforge.utils.terminal_plot import TerminalPlotter
except ImportError:
    _QFORGE_AVAILABLE = False
    print("Warning: qforge modules not found. Running in UI testing mode.")

    __version__ = "0.0.0"

    class _Stub:
        def __init__(self, *a, **kw): pass
        def __call__(self, *a, **kw): return self
        def __getattr__(self, _): return self
        def load_session(self): pass
        def list_qubits(self): return []

    QubitEngine = GateEngine = PhysicalWorkflowEngine = ErrorCorrectionEngine = _Stub
    TerminalPlotter = _Stub
    QUBIT_PRESETS = {"transmon": {"typical": {"EJ": 15.0, "EC": 0.2, "ng": 0.0, "ncut": 30}}}
    OUTPUT_DIRS = {"base": "outputs"}
    REPETITION_3 = STEANE_7 = SHOR_9 = None
    def list_example_files(): return []
    def get_examples_dir(): return "."
    def _create_qubit(*a, **kw): print("(stub) _create_qubit called")
    class _FakeCmd:
        @staticmethod
        def callback(**kw): print(f"(stub) callback called with {kw}")
    list_qubits = analyze = delete = simulate = compare_qubits = _FakeCmd()

# Error-correcting codes offered by the full workflow wizard, and the
# ErrorCorrectionEngine entry point each one runs through. Each dedicated
# method (rather than the generic execute_stabilizer_workflow) reclaims
# ancilla dimension as it goes, which is what keeps Steane and Shor
# tractable at their larger qubit counts per logical block.
EC_CODE_MAP = {
    "3-qubit repetition code": (REPETITION_3, "execute_3q_repetition_workflow"),
    "7-qubit Steane code": (STEANE_7, "execute_steane7_workflow"),
    "9-qubit Shor code": (SHOR_9, "execute_shor9_workflow"),
}
EC_LABELS = ["No error correction"] + list(EC_CODE_MAP.keys())


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
#  Multi-select dialog                                                          #
# --------------------------------------------------------------------------- #

class MultiSelectDialog(tk.Toplevel):
    """
    A themed modal dialog for picking several items at once: a live-filter
    Entry, a multi-select Listbox, "Select all" / "Select none" shortcuts,
    and OK / Cancel. Selections survive filtering (they're tracked by value,
    not by row index), so narrowing the list and then clearing the filter
    never silently drops a pick.

    Returns the chosen items as a list in their original order, or None if
    the user cancelled.
    """

    def __init__(self, parent, title: str, prompt: str, choices: list, preselected=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(True, True)
        self.configure(bg=C["pick_bg"])
        self.result: list | None = None

        self.transient(parent)
        self.grab_set()

        self._choices = list(choices)
        self._selected = set(preselected or [])
        self._displayed = list(self._choices)

        max_item_len = max((len(c) for c in choices), default=20)
        computed_w = max(420, min(680, max_item_len * 8 + 100))

        self._build_ui(prompt, computed_w)

        list_h = min(10, max(4, len(choices)))
        approx_h = 300 + list_h * 20
        self.geometry(f"{computed_w}x{approx_h}")
        self.update_idletasks()

        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"{computed_w}x{approx_h}+{px}+{py}")

        self._entry.focus_set()
        self.bind("<Escape>", lambda _: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window()

    # ------------------------------------------------------------------ #

    def _build_ui(self, prompt: str, dlg_width: int):
        PAD = 16
        wrap_w = dlg_width - PAD * 2

        tk.Label(
            self, text=prompt,
            bg=C["pick_bg"], fg=C["accent"],
            font=("Helvetica", 11),
            justify="left", anchor="w", wraplength=wrap_w,
        ).pack(fill=tk.X, padx=PAD, pady=(PAD, 8))

        tk.Label(
            self, text="🔍  Filter",
            bg=C["pick_bg"], fg=C["fg_dim"],
            font=("Helvetica", 9), anchor="w",
        ).pack(fill=tk.X, padx=PAD, pady=(0, 2))

        entry_frame = tk.Frame(self, bg=C["pick_border"], padx=1, pady=1)
        entry_frame.pack(fill=tk.X, padx=PAD, pady=(0, 6))
        self._entry = tk.Entry(
            entry_frame, bg=C["pick_entry"], fg=C["accent"],
            insertbackground=C["accent"], relief="flat",
            font=("Consolas", 12), bd=0,
        )
        self._entry.pack(fill=tk.X, padx=6, pady=6)
        self._entry.bind("<KeyRelease>", self._on_filter)
        self._entry.bind("<Down>", lambda _: self._focus_list())

        action_row = tk.Frame(self, bg=C["pick_bg"])
        action_row.pack(fill=tk.X, padx=PAD, pady=(0, 4))
        select_all = tk.Label(
            action_row, text="Select all", bg=C["pick_bg"], fg=C["accent"],
            font=("Helvetica", 9, "underline"), cursor="hand2",
        )
        select_all.pack(side=tk.LEFT)
        select_all.bind("<Button-1>", lambda _: self._select_all())
        select_none = tk.Label(
            action_row, text="Select none", bg=C["pick_bg"], fg=C["fg_dim"],
            font=("Helvetica", 9, "underline"), cursor="hand2",
        )
        select_none.pack(side=tk.RIGHT)
        select_none.bind("<Button-1>", lambda _: self._select_none())

        list_frame = tk.Frame(self, bg=C["pick_border"], padx=1, pady=1)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(0, 6))

        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                          bg=C["bg_card"], troughcolor=C["pick_bg"],
                          width=10, relief="flat")
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._listbox = tk.Listbox(
            list_frame, selectmode=tk.MULTIPLE, exportselection=False,
            bg=C["bg_console"], fg=C["fg"],
            selectbackground=C["pick_sel"], selectforeground=C["accent"],
            activestyle="none", font=("Consolas", 12),
            relief="flat", bd=0, yscrollcommand=sb.set,
            height=min(10, max(4, len(self._choices))),
        )
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self._listbox.bind("<Return>", lambda _: self._ok())

        self._count_var = tk.StringVar()
        tk.Label(
            self, textvariable=self._count_var,
            bg=C["pick_bg"], fg=C["fg_dim"],
            font=("Helvetica", 9), anchor="w",
        ).pack(fill=tk.X, padx=PAD, pady=(0, 4))

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

        self._populate(self._choices)

    # ------------------------------------------------------------------ #

    def _sync_from_listbox(self):
        """Fold the listbox's current visual selection into the master set."""
        sel_indices = set(self._listbox.curselection())
        for i, item in enumerate(self._displayed):
            if i in sel_indices:
                self._selected.add(item)
            else:
                self._selected.discard(item)

    def _populate(self, items: list):
        self._displayed = list(items)
        self._listbox.delete(0, tk.END)
        for item in items:
            self._listbox.insert(tk.END, f"  {item}")
        for i, item in enumerate(items):
            if item in self._selected:
                self._listbox.selection_set(i)
        self._update_count()

    def _update_count(self):
        self._count_var.set(f"{len(self._selected)} of {len(self._choices)} selected")

    def _on_listbox_select(self, _event=None):
        self._sync_from_listbox()
        self._update_count()

    def _on_filter(self, _event=None):
        self._sync_from_listbox()
        query = self._entry.get().strip().lower()
        filtered = [c for c in self._choices if query in c.lower()] if query else self._choices
        self._populate(filtered)

    def _focus_list(self):
        if self._listbox.size():
            self._listbox.focus_set()

    def _select_all(self):
        self._selected.update(self._displayed)
        self._listbox.selection_set(0, tk.END)
        self._update_count()

    def _select_none(self):
        for item in self._displayed:
            self._selected.discard(item)
        self._listbox.selection_clear(0, tk.END)
        self._update_count()

    def _ok(self):
        self._sync_from_listbox()
        self.result = [c for c in self._choices if c in self._selected]
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# --------------------------------------------------------------------------- #
#  Confirm / notice dialogs                                                     #
# --------------------------------------------------------------------------- #

class ConfirmDialog(tk.Toplevel):
    """A themed Yes / No confirmation, replacing tkinter.messagebox.askyesno."""

    def __init__(self, parent, title: str, message: str,
                 confirm_text="Yes", cancel_text="No",
                 danger: bool = False, default: bool = True):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=C["pick_bg"])
        self.result = False

        self.transient(parent)
        self.grab_set()

        accent_color = C["red"] if danger else C["accent"]
        icon = "⚠" if danger else "❓"

        PAD = 20
        row = tk.Frame(self, bg=C["pick_bg"])
        row.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(PAD, 8))

        tk.Label(row, text=icon, bg=C["pick_bg"], fg=accent_color,
                 font=("Helvetica", 22)).pack(side=tk.LEFT, padx=(0, 14), anchor="n")
        tk.Label(row, text=message, bg=C["pick_bg"], fg=C["fg"],
                 font=("Helvetica", 11), justify="left", anchor="w",
                 wraplength=340).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_row = tk.Frame(self, bg=C["pick_bg"])
        btn_row.pack(fill=tk.X, padx=PAD, pady=(4, PAD))

        cancel_btn = tk.Button(
            btn_row, text=cancel_text,
            bg=C["bg_card"], fg=C["fg_sub"],
            activebackground=C["bg_card"], activeforeground=C["fg"],
            relief="flat", font=("Helvetica", 10),
            padx=16, pady=6, cursor="hand2", command=self._no,
        )
        cancel_btn.pack(side=tk.RIGHT)

        confirm_btn = tk.Button(
            btn_row, text=confirm_text,
            bg=(C["red"] if danger else C["accent2"]), fg=C["fg"],
            activebackground=accent_color, activeforeground=C["fg"],
            relief="flat", font=("Helvetica", 10, "bold"),
            padx=16, pady=6, cursor="hand2", command=self._yes,
        )
        confirm_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self.bind("<Return>", lambda _: (self._yes() if default else self._no()))
        self.bind("<Escape>", lambda _: self._no())
        self.protocol("WM_DELETE_WINDOW", self._no)

        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")

        (confirm_btn if default else cancel_btn).focus_set()
        self.wait_window()

    def _yes(self):
        self.result = True
        self.destroy()

    def _no(self):
        self.result = False
        self.destroy()


_NOTICE_STYLE = {
    "info":    ("ℹ", C["accent"]),
    "success": ("✓", C["green"]),
    "warning": ("⚠", C["yellow"]),
    "error":   ("✗", C["red"]),
}


class NoticeDialog(tk.Toplevel):
    """A themed, single-button notice, replacing messagebox.showinfo/warning/error."""

    def __init__(self, parent, title: str, message: str, kind: str = "info"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=C["pick_bg"])

        self.transient(parent)
        self.grab_set()

        icon, color = _NOTICE_STYLE.get(kind, _NOTICE_STYLE["info"])

        PAD = 20
        row = tk.Frame(self, bg=C["pick_bg"])
        row.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(PAD, 8))

        tk.Label(row, text=icon, bg=C["pick_bg"], fg=color,
                 font=("Helvetica", 22)).pack(side=tk.LEFT, padx=(0, 14), anchor="n")
        tk.Label(row, text=message, bg=C["pick_bg"], fg=C["fg"],
                 font=("Helvetica", 11), justify="left", anchor="w",
                 wraplength=340).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_row = tk.Frame(self, bg=C["pick_bg"])
        btn_row.pack(fill=tk.X, padx=PAD, pady=(4, PAD))
        ok_btn = tk.Button(
            btn_row, text="  OK  ",
            bg=C["accent2"], fg=C["fg"],
            activebackground=C["accent"], activeforeground=C["fg"],
            relief="flat", font=("Helvetica", 10, "bold"),
            padx=16, pady=6, cursor="hand2", command=self.destroy,
        )
        ok_btn.pack(side=tk.RIGHT)

        self.bind("<Return>", lambda _: self.destroy())
        self.bind("<Escape>", lambda _: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")
        ok_btn.focus_set()
        self.wait_window()


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

        self._logo_img = self._load_logo(base_dir)

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
        top = tk.Frame(self, bg=C["bg_panel"], height=48)
        top.pack(fill=tk.X, side=tk.TOP)
        top.pack_propagate(False)

        tk.Frame(top, bg=C["accent2"], width=3).pack(side=tk.LEFT, fill=tk.Y)

        brand = tk.Frame(top, bg=C["bg_panel"])
        brand.pack(side=tk.LEFT, padx=(10, 0), pady=6)

        if self._logo_img is not None:
            tk.Label(brand, image=self._logo_img, bg=C["bg_panel"]).pack(side=tk.LEFT)
        else:
            tk.Label(
                brand, text="⚛  qforge",
                bg=C["bg_panel"], fg=C["accent"],
                font=("Helvetica", 14, "bold"),
            ).pack(side=tk.LEFT)

        tk.Label(
            top, text=" quantum simulation environment",
            bg=C["bg_panel"], fg=C["fg_sub"],
            font=("Helvetica", 11),
        ).pack(side=tk.LEFT, pady=8)

        version_lbl = tk.Label(
            top, text=f"v{__version__} ",
            bg=C["bg_panel"], fg=C["fg_dim"],
            font=("Helvetica", 9),
        )
        version_lbl.pack(side=tk.RIGHT, pady=8, padx=12)

        docs_lbl = tk.Label(
            top, text="Documentation ↗",
            bg=C["bg_panel"], fg=C["accent"],
            font=("Helvetica", 10, "underline"), cursor="hand2",
        )
        docs_lbl.pack(side=tk.RIGHT, pady=8, padx=4)
        docs_lbl.bind("<Button-1>", lambda _: self._open_docs())

        # ── Main pane ─────────────────────────────────────────────────── #
        self.main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar (scrollable, so it never clips as more sections grow) ─ #
        sidebar = tk.Frame(self.main_paned, bg=C["bg_panel"], width=250)
        self.main_paned.add(sidebar, weight=0)

        nav_canvas = tk.Canvas(sidebar, bg=C["bg_panel"], highlightthickness=0)
        nav_scroll = ttk.Scrollbar(
            sidebar, orient=tk.VERTICAL, command=nav_canvas.yview,
            style="Console.Vertical.TScrollbar",
        )
        nav_canvas.configure(yscrollcommand=nav_scroll.set)
        nav_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        nav_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        inner = tk.Frame(nav_canvas, bg=C["bg_panel"])
        inner_window = nav_canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event=None):
            nav_canvas.configure(scrollregion=nav_canvas.bbox("all"))

        def _on_canvas_configure(event):
            nav_canvas.itemconfig(inner_window, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        nav_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_nav_wheel(event):
            nav_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(_event=None):
            nav_canvas.bind_all("<MouseWheel>", _on_nav_wheel)

        def _unbind_wheel(_event=None):
            nav_canvas.unbind_all("<MouseWheel>")

        nav_canvas.bind("<Enter>", _bind_wheel)
        nav_canvas.bind("<Leave>", _unbind_wheel)

        sections = [
            ("QUBITS", [
                ("➕   Create a qubit",   self._wizard_create_qubit),
                ("📋   List qubits",      self._wizard_list_qubits),
                ("🔬   Analyze a qubit",  self._wizard_analyze_qubit),
                ("⚖   Compare qubits",   self._wizard_compare_qubits),
                ("🗑   Delete a qubit",   self._wizard_delete_qubit),
            ]),
            ("GATES & CIRCUITS", [
                ("⚡   Simulate a gate",           self._wizard_simulate_gate),
                ("🔀   Multi-qubit gate analysis", self._wizard_analyze_multi),
                ("🔗   Build a circuit",           self._wizard_build_circuit),
            ]),
            ("WORKFLOWS", [
                ("🚀   Run full workflow", self._wizard_full_workflow),
            ]),
            ("HARDWARE", [
                ("🖥   Design hardware", self._wizard_design_hardware),
            ]),
            ("LEARN", [
                ("▶   Run an example",     self._wizard_run_example),
                ("❓   Help",               self._show_help),
                ("📖   Documentation",     self._open_docs),
            ]),
            ("SYSTEM", [
                ("🧹   Clear calibration cache", self._wizard_clear_cache),
            ]),
        ]

        for header, buttons in sections:
            ttk.Label(inner, text=header, style="SidebarHeader.TLabel").pack(
                fill=tk.X, padx=14, pady=(12, 2)
            )
            tk.Frame(inner, bg=C["accent2"], height=1).pack(fill=tk.X, padx=14, pady=(0, 4))
            for text, cmd in buttons:
                ttk.Button(inner, text=text, command=cmd, style="Nav.TButton").pack(
                    fill=tk.X, padx=6, pady=1
                )

        tk.Frame(inner, bg=C["separator"], height=1).pack(fill=tk.X, padx=14, pady=(10, 4))
        ttk.Button(inner, text="✕   Exit", command=self._safe_quit,
                   style="Danger.TButton").pack(fill=tk.X, padx=6, pady=(2, 12))

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
            self.main_paned.sashpos(0, 250)
        except Exception:
            pass

    def _clear_console(self):
        self.console_text.delete("1.0", tk.END)

    def _load_logo(self, base_dir: str):
        """
        Load the qforge wordmark for the top bar, downscaled to a sensible
        height. Uses Tk's native PNG support (no Pillow dependency needed).
        Returns None if the asset is missing or can't be read, so the top
        bar falls back to a text brand instead of failing to start.
        """
        logo_path = os.path.join(base_dir, "assets", "icon.png")
        if not os.path.exists(logo_path):
            return None
        try:
            img = tk.PhotoImage(file=logo_path)
            target_h = 30
            factor = max(1, -(-img.height() // target_h))  # ceil division
            if factor > 1:
                img = img.subsample(factor, factor)
            return img
        except Exception:
            return None

    def _open_docs(self):
        try:
            webbrowser.open(DOCS_URL)
            self._dim(f"Opened documentation: {DOCS_URL}")
        except Exception as e:
            self._err(f"Could not open the browser: {e}")

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

    def _ask_multi(self, title: str, prompt_text: str,
                   choices: list, preselected=None) -> "list | None":
        """
        Multi-select picker: checkbox-style list with a live filter.
        Returns the chosen items as a list, or None if cancelled.
        """
        dlg = MultiSelectDialog(self, title, prompt_text, choices, preselected)
        return dlg.result

    def _confirm(self, title: str, message: str, danger: bool = False,
                default: bool = True) -> bool:
        """
        Themed Yes / No confirmation. Safe to call from the main thread or
        from a background worker thread (wizards run their engine calls on
        a worker thread via `_run_in_thread`, and Tkinter widgets may only
        be created on the main thread, so a cross-thread call schedules the
        dialog on the main thread and blocks the caller until it closes).
        """
        if threading.current_thread() is threading.main_thread():
            return ConfirmDialog(self, title, message, danger=danger, default=default).result

        box = {}
        event = threading.Event()

        def _show():
            box["value"] = ConfirmDialog(self, title, message, danger=danger, default=default).result
            event.set()

        self.after(0, _show)
        event.wait()
        return box.get("value", False)

    def _notify(self, title: str, message: str, kind: str = "info") -> None:
        """Themed notice dialog (info / success / warning / error). Thread-safe, see `_confirm`."""
        if threading.current_thread() is threading.main_thread():
            NoticeDialog(self, title, message, kind=kind)
            return

        event = threading.Event()

        def _show():
            NoticeDialog(self, title, message, kind=kind)
            event.set()

        self.after(0, _show)
        event.wait()

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
                self._notify("Success", f"Qubit '{name}' created successfully.", kind="success")
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
            self._notify("No qubits", "No qubits found. Create one first.", kind="warning")
            return

        name = self._ask_choice(
            "Analyze Qubit", "Select qubit to analyze:", qubits
        )
        if not name:
            self._warn("Aborted.")
            return
        name = name.strip()

        do_plot = self._confirm("Plot", "Generate plots?", default=True)
        do_coherence = self._confirm("Coherence", "Estimate coherence?", default=True)
        do_relative = self._confirm("Relative energy", "Display energies relative to the ground state?", default=False)

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
            self._notify("No qubits", "No qubits to delete.", kind="warning")
            return

        name = self._ask_choice(
            "Delete Qubit", "Select qubit to delete:", qubits
        )
        if not name:
            self._warn("Aborted.")
            return
        name = name.strip()

        if not self._confirm(
            "Confirm deletion",
            f"Delete '{name}'? This cannot be undone.",
            danger=True, default=False,
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
                self._notify("Deleted", f"'{name}' has been deleted.", kind="success")
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
            self._notify("No qubits", "No qubits found. Create one first.", kind="warning")
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
                self._notify(
                    "Need more qubits",
                    "You need at least two qubits for a two-qubit gate.",
                    kind="warning",
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
                    do_save = self._confirm("Save plot", "Save a high-resolution plot to file?", default=False)
                    if do_save:
                        self._dim("Re-running to save a high-resolution plot...")
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
        if len(qubits) < 2:
            self._notify("No qubits", "Need at least two qubits to compare.", kind="warning")
            return

        picked = self._ask_multi(
            "Compare Qubits",
            "Tick every qubit you want in the comparison:",
            qubits,
        )
        if not picked:
            self._warn("Aborted.")
            return
        if len(picked) < 2:
            self._notify("Pick more qubits", "Select at least two qubits to compare.", kind="warning")
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
                    qubits=",".join(picked), metrics=metrics,
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
            self._notify(
                "Need more qubits",
                "You need at least two qubits for multi-qubit gate analysis.",
                kind="warning",
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

        do_tomo = self._confirm("State tomography", "Perform state tomography (fidelity check)?", default=False)

        self._cprint(
            f"\n[green]Running coupling comparison for "
            f"[bold]{gate}[/bold] on [cyan]{q1}[/cyan] → [cyan]{q2}[/cyan]...[/green]"
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
                    self._dim("  Note: 'Target Pop' is P(|11⟩), the bit-flip success probability.")
                elif gate == "CZ":
                    self._dim("  Note: 'Target Pop' is P(|11⟩), a population retention / leakage proxy.")

                if do_tomo:
                    self._dim("  (Detailed tomography is a future integration point.)")

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
            self._notify("Not found", f"Example '{ex_name}' not found.", kind="error")
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
            self._notify("No qubits", "No qubits exist. Create qubits first.", kind="warning")
            return

        # ── Step 1: qubit selection ──────────────────────────────────── #
        print("[bold]1. Select qubits[/bold]")
        qubit_names = self._ask_multi(
            "Select Qubits",
            "Tick every qubit this workflow should use:",
            available_qubits,
        )
        if not qubit_names:
            self._warn("No qubits selected. Aborted.")
            return
        print(f"  [green]Using:[/green] [cyan]{', '.join(qubit_names)}[/cyan]")

        # ── Step 2: coupling topology ─────────────────────────────────── #
        print("\n[bold]2. Define native coupling topology[/bold]")
        print("[dim]   Couplings are bidirectional. Specify each Q1-Q2 edge only once.[/dim]")
        couplings = []
        c_type_choices = ["capacitive", "inductive", "tunable_coupler"]

        while self._confirm(
            "Add coupling edge",
            f"Qubits: {', '.join(qubit_names)}\n\nAdd a native coupling edge?",
            default=False,
        ):
            q1_input = self._ask_choice(
                "Coupling: first qubit",
                "Select the first qubit in the edge:",
                qubit_names,
            )
            if not q1_input:
                break
            q1_input = q1_input.strip()

            q2_choices = [q for q in qubit_names if q != q1_input]
            q2_input = self._ask_choice(
                "Coupling: second qubit",
                f"Select the second qubit, paired with {q1_input}:",
                q2_choices,
            )
            if not q2_input:
                break
            q2_input = q2_input.strip()

            if q1_input not in qubit_names or q2_input not in qubit_names:
                self._notify("Invalid", f"'{q1_input}' or '{q2_input}' is not in the selected list.", kind="error")
                continue

            ctype = self._ask_choice(
                "Coupling type", "Select coupling type:",
                c_type_choices, "tunable_coupler",
            )
            if ctype is None:
                break
            ctype = ctype.strip() or "tunable_coupler"

            cstren_str = self._ask_string("Coupling strength", "Strength (GHz):", "0.05")
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

        # ── Step 3: error correction ─────────────────────────────────── #
        print("\n[bold]3. Error correction[/bold]")
        ecc_choice = self._ask_choice(
            "Error Correction",
            "Select the error-correcting code to use for this workflow:",
            EC_LABELS,
            "No error correction",
        )
        if ecc_choice is None:
            self._warn("Aborted.")
            return
        ecc_choice = ecc_choice.strip() or "No error correction"

        ec_coupling_type = "capacitive"
        ec_coupling_strength = 0.010
        ec_every_n_gates = 0

        if ecc_choice != "No error correction":
            code, _method_name = EC_CODE_MAP[ecc_choice]
            per_logical = code.num_data + code.num_ancilla
            n_physical = len(qubit_names) * per_logical
            print(
                f"[dim]   {code.name}: each logical qubit expands to {per_logical} physical "
                f"qubits ({code.num_data} data + {code.num_ancilla} ancilla). "
                f"{len(qubit_names)} logical qubit(s) -> {n_physical} physical qubits total.[/dim]"
            )
            if n_physical > 20 and not self._confirm(
                "Large simulation",
                f"That is a {2 ** n_physical:,}-dimensional state vector.\n"
                "This may be slow or memory-heavy. Continue anyway?",
                danger=True, default=False,
            ):
                self._warn("Aborted.")
                return

            ec_ctype = self._ask_choice(
                "Syndrome coupling type",
                "Coupling type for syndrome-extraction CNOTs:",
                c_type_choices, "capacitive",
            )
            ec_coupling_type = (ec_ctype or "capacitive").strip() or "capacitive"

            ec_g_str = self._ask_string("Syndrome coupling strength", "Strength (GHz):", "0.010")
            try:
                ec_coupling_strength = float((ec_g_str or "0.010").strip() or "0.010")
            except ValueError:
                self._err("Invalid strength; using 0.010 GHz.")
                ec_coupling_strength = 0.010

            ec_n_str = self._ask_string(
                "Syndrome cycle cadence",
                "Run a syndrome cycle every N gates (0 = only a final pass, safest with H gates):",
                "0",
            )
            try:
                ec_every_n_gates = int((ec_n_str or "0").strip() or "0")
            except ValueError:
                self._err("Invalid value; using 0 (final pass only).")
                ec_every_n_gates = 0

        # ── Step 4: QASM source ──────────────────────────────────────── #
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
            self._notify("File not found", f"QASM file not found:\n{qasm_path}", kind="error")
            self._err(f"QASM file '{qasm_path}' not found.")
            return

        print("\n[dim]Initializing workflow engines...[/dim]")

        def _do():
            try:
                g_eng = GateEngine()
                if ecc_choice != "No error correction":
                    code, method_name = EC_CODE_MAP[ecc_choice]
                    ec_eng = ErrorCorrectionEngine(self.engine, g_eng)
                    method = getattr(ec_eng, method_name)
                    print(f"[cyan]Using ErrorCorrectionEngine ({code.name})...[/cyan]")
                    res = method(
                        qubit_names, qasm_path,
                        coupling_type=ec_coupling_type,
                        coupling_strength=ec_coupling_strength,
                        ec_every_n_gates=ec_every_n_gates,
                    )
                    logical_results = res["logical_populations"]
                    print("\n[bold green]Workflow complete.[/bold green]  "
                          "[dim]Decoded logical populations:[/dim]")
                    for l_state, prob in sorted(logical_results.items(), key=lambda x: -x[1]):
                        if prob > 0.001:
                            print(f"  [cyan]|{l_state}⟩_L[/cyan]  [orange]{prob * 100:5.2f}%[/orange]")
                    self._dim(
                        "\nNote: timeline plotting is skipped during active error correction, "
                        "since mid-circuit syndrome measurement collapses the wavefunction."
                    )
                else:
                    print("[cyan]Using PhysicalWorkflowEngine...[/cyan]")
                    wf_eng = PhysicalWorkflowEngine(self.engine, g_eng)
                    res    = wf_eng.execute_workflow(qubit_names, couplings, qasm_path)
                    print("\n[bold green]Simulation complete.[/bold green]  "
                          "[dim]Physical populations:[/dim]")
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
                        print("\n[bold]Visual hardware timeline:[/bold]")
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
                traceback.print_exc()

        self._run_in_thread(_do, done_msg="Workflow complete.")

    # ---------------------------------------------------------------------- #
    #  Wizard: Clear calibration cache                                         #
    # ---------------------------------------------------------------------- #

    def _wizard_clear_cache(self):
        self._header("Clear Calibration Cache")

        g_eng = GateEngine()
        n_cached = len(GateEngine._calib_cache)
        cache_path = getattr(
            g_eng, "cache_file",
            os.path.join(OUTPUT_DIRS.get("data", "outputs"), "calib_cache.json"),
        )

        self._dim(f"Cache file: {cache_path}")

        if n_cached == 0 and not os.path.exists(cache_path):
            self._notify("Cache already empty", "There is no calibration cache to clear.", kind="info")
            return

        print(f"[bold]{n_cached}[/bold] calibration(s) currently cached in this session.")

        plural = "" if n_cached == 1 else "s"
        if not self._confirm(
            "Clear calibration cache",
            f"This forgets {n_cached} cached gate calibration{plural}.\n"
            "qforge simply recalibrates the next time it needs one, so nothing "
            "is lost, it just takes a little longer next time.\n\n"
            "Clear the cache now?",
            default=False,
        ):
            self._dim("Cache clear cancelled.")
            return

        try:
            GateEngine._calib_cache.clear()
            g_eng._save_cache_to_disk()
            self._ok(f"Calibration cache cleared ({n_cached} entr{'y' if n_cached == 1 else 'ies'} removed).")
            self._notify("Cache cleared", "The calibration cache has been cleared.", kind="success")
        except Exception as e:
            self._err(f"Could not clear cache: {e}")

    # ---------------------------------------------------------------------- #
    #  Help                                                                    #
    # ---------------------------------------------------------------------- #

    def _show_help(self):
        self._header("qforge Help")
        print(f"""
[bold]Navigation[/bold]
  [dim]·[/dim] Click a button on the left panel to launch a guided wizard.
  [dim]·[/dim] Where a step needs several qubits, tick them in the picker and press OK.
  [dim]·[/dim] Type to filter any searchable list, it narrows as you type.
  [dim]·[/dim] All output, errors, and plots appear in this console.
  [dim]·[/dim] Use the [cyan]Clear[/cyan] link above the console to reset its output.

[bold]Workflow reference[/bold]
  [cyan] 1.[/cyan] [green]Create a qubit[/green]             Define the physical parameters of a superconducting qubit.
  [cyan] 2.[/cyan] [green]List qubits[/green]                 View every qubit saved in the current session.
  [cyan] 3.[/cyan] [green]Analyze a qubit[/green]             Energy spectrum, coherence estimates, and plots.
  [cyan] 4.[/cyan] [green]Compare qubits[/green]              Side-by-side metrics across several qubits at once.
  [cyan] 5.[/cyan] [green]Delete a qubit[/green]              Remove a qubit and clear its calibration cache.
  [cyan] 6.[/cyan] [green]Simulate a gate[/green]             Model 1-qubit (X/Y/Z/H) or 2-qubit (CNOT/CZ) dynamics.
  [cyan] 7.[/cyan] [green]Multi-qubit gate analysis[/green]   Compare coupling strategies for a 2-qubit gate.
  [cyan] 8.[/cyan] [green]Build a circuit[/green]             [dim](coming soon)[/dim] Construct and simulate a circuit.
  [cyan] 9.[/cyan] [green]Run full workflow[/green]           QASM in, physical execution out, with optional error correction.
  [cyan]10.[/cyan] [green]Design hardware[/green]             [dim](coming soon)[/dim] Lay out a quantum chip.
  [cyan]11.[/cyan] [green]Run an example[/green]              Run a bundled example script.
  [cyan]12.[/cyan] [green]Clear calibration cache[/green]     Forget cached gate calibrations, with a confirmation first.

[bold]Error correction[/bold]
  Run full workflow now offers three codes, each mapping every logical
  qubit onto more physical qubits so it can detect and correct errors:
  [dim]·[/dim] [cyan]3-qubit repetition code[/cyan]   5 physical qubits per logical qubit, corrects a single bit flip.
  [dim]·[/dim] [cyan]7-qubit Steane code[/cyan]       13 physical qubits per logical qubit, corrects any single-qubit Pauli error.
  [dim]·[/dim] [cyan]9-qubit Shor code[/cyan]         17 physical qubits per logical qubit, corrects any single-qubit error.

[bold]Tips[/bold]
  [dim]·[/dim] Start with [cyan]Create a qubit[/cyan] if you are new here.
  [dim]·[/dim] Accept the default parameter values for a quick sanity check.
  [dim]·[/dim] Bundled example circuits live under [cyan]examples/qasm_files[/cyan].
  [dim]·[/dim] For the command-line reference, run [cyan]qforge --help[/cyan].
  [dim]·[/dim] Full documentation: [cyan]{DOCS_URL}[/cyan] (also one click away at the top of this window).
""")


# --------------------------------------------------------------------------- #
#  Entry point                                                                 #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    app = QForgeGUI()
    app.protocol("WM_DELETE_WINDOW", app._safe_quit)
    app.mainloop()
