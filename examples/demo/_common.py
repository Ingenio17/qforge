"""
Shared plumbing for the demo suite: plotting style, tables, checks and a workspace.

Every demo writes to demo_plots/<demo name>/ and runs in a private scratch directory,
so nothing here touches the qubits registered in your own session. Every demo also
compares itself with an independent calculation through :class:`Demo.check`, and
fails loudly if the two disagree.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
warnings.filterwarnings("ignore")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "demo_plots"
DEVICES = REPO / "examples" / "device_files"
CIRCUITS = REPO / "examples" / "qasm_files"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# --- palette (categorical order is the colour-blind-safety mechanism) ---------
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
MAGENTA, GREEN, VIOLET, RED = "#e87ba4", "#008300", "#6250d6", "#e34948"
SERIES = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]
SURFACE, INK, INK2, MUTED, GRID, AXIS = (
    "#fcfcfb",
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
)
SEQUENTIAL = LinearSegmentedColormap.from_list(
    "qw_seq", [SURFACE, "#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]
)
DIVERGING = LinearSegmentedColormap.from_list(
    "qw_div", ["#0d366b", "#2a78d6", "#9ec5f4", "#f0efec", "#f2a9a8", "#e34948", "#7d1a1a"]
)

plt.rcParams.update(
    {
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 11,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.labelcolor": INK2,
        "axes.titlecolor": INK,
        "axes.titlesize": 12.5,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK2,
        "ytick.labelcolor": INK2,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "lines.markersize": 7,
        "lines.markeredgecolor": SURFACE,
        "lines.markeredgewidth": 1.5,
        "legend.frameon": False,
        "legend.labelcolor": INK2,
        "legend.fontsize": 10,
        "mathtext.fontset": "dejavusans",
    }
)


def headline(fig, title: str, subtitle: str, top: float = 0.86) -> None:
    """Figure-level title and one-line takeaway, left aligned."""
    height = fig.get_figheight()
    fig.suptitle(title, x=0.012, y=1 - 0.12 / height, ha="left", va="top", fontsize=17,
                 fontweight="bold", color=INK)
    fig.text(0.012, 1 - 0.50 / height, subtitle, ha="left", va="top", fontsize=11.5, color=INK2)


def heatmap_axes(ax) -> None:
    ax.grid(False)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)


def colorbar(fig, image, ax, label: str, **kwargs):
    bar = fig.colorbar(image, ax=ax, pad=0.02, fraction=0.046, **kwargs)
    bar.set_label(label, color=INK2)
    bar.outline.set_visible(False)
    bar.ax.tick_params(color=MUTED)
    return bar


@contextlib.contextmanager
def quiet():
    """Silence engine progress output."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


class Demo:
    """One demo: where its artefacts go, what it tabulated and what it checked."""

    def __init__(self, name: str, title: str):
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        self.name, self.title = name, title
        self.folder = OUTPUT / name
        self.folder.mkdir(parents=True, exist_ok=True)
        self.checks: list[dict] = []
        self.started = time.time()
        workspace = Path(tempfile.gettempdir()) / "qubitweave_demo" / name
        workspace.mkdir(parents=True, exist_ok=True)
        os.chdir(workspace)
        print(f"\n=== {title} ===")

    def save(self, fig, stem: str) -> None:
        path = self.folder / f"{stem}.png"
        fig.savefig(path, dpi=200)
        plt.close(fig)
        print(f"  plot   {path.relative_to(REPO)}")

    def table(self, frame: pd.DataFrame, stem: str, caption: str) -> None:
        """Write a table as CSV, Markdown and a presentation-ready PNG."""
        frame.to_csv(self.folder / f"{stem}.csv", index=False)
        text = frame.astype(str)
        # A ket like |00> would otherwise read as a column separator.
        cells = [[c.replace("|", "\\|") for c in row] for row in [text.columns, *text.values]]
        lines = [f"**{caption}**", ""] + ["| " + " | ".join(row) + " |" for row in cells]
        lines.insert(3, "|" + "|".join("---" for _ in text.columns) + "|")
        (self.folder / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._table_png(text, stem, caption)
        print(f"  table  {(self.folder / stem).relative_to(REPO)}.csv / .md / .png")

    def _table_png(self, text: pd.DataFrame, stem: str, caption: str) -> None:
        cells = [list(text.columns)] + text.values.tolist()
        char, pad, row_height = 0.092, 0.30, 0.34
        widths = [max(len(str(row[c])) for row in cells) * char + pad for c in range(text.shape[1])]
        width = max(sum(widths) + 0.5, len(caption) * 0.105 + 0.5)
        height = row_height * len(cells) + 0.75
        fig = plt.figure(figsize=(width, height))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, width)
        ax.set_ylim(0, height)
        ax.axis("off")
        ax.text(0.25, height - 0.28, caption, fontsize=12, fontweight="bold", color=INK, va="center")
        numeric = [
            pd.to_numeric(
                text.iloc[:, c].str.replace(r"[%,+±]|[^\x00-\x7f]", "", regex=True), errors="coerce"
            ).notna().all()
            for c in range(text.shape[1])
        ]
        y = height - 0.72
        for r, row in enumerate(cells):
            x = 0.25
            for c, value in enumerate(row):
                right = numeric[c]
                ax.text(
                    x + widths[c] - pad if right else x,
                    y,
                    str(value).replace("$", r"\$"),
                    ha="right" if right else "left",
                    va="center",
                    fontsize=10,
                    color=INK2 if r == 0 else INK,
                    fontweight="semibold" if r == 0 else "normal",
                )
                x += widths[c]
            ax.plot([0.25, 0.25 + sum(widths) - pad / 2], [y - row_height / 2] * 2,
                    color=AXIS if r == 0 else GRID, lw=1.0 if r == 0 else 0.6)
            y -= row_height
        fig.savefig(self.folder / f"{stem}.png", dpi=200)
        plt.close(fig)

    def check(self, what: str, got: float, expected: float, tolerance: float) -> None:
        """Record a comparison with an independent value."""
        ok = abs(got - expected) <= tolerance
        self.checks.append(
            {
                "check": what,
                "result": f"{got:.6g}",
                "expected": f"{expected:.6g}",
                "tolerance": f"{tolerance:.2g}",
                "status": "PASS" if ok else "FAIL",
            }
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {what}: {got:.6g} (expected {expected:.6g} ± {tolerance:.2g})")

    def finish(self) -> bool:
        pd.DataFrame(self.checks).to_csv(self.folder / "checks.csv", index=False)
        failed = [c for c in self.checks if c["status"] != "PASS"]
        print(f"  {len(self.checks) - len(failed)}/{len(self.checks)} checks passed "
              f"in {time.time() - self.started:.0f} s")
        if failed:
            raise SystemExit(f"{self.name}: {len(failed)} check(s) failed")
        return True
