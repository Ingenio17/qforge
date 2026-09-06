"""
Developer CLI commands for qforge.
"""

import click
from rich.console import Console
from pathlib import Path
from qforge.config.defaults import QUBIT_PRESETS

console = Console()

@click.group()
def dev():
    """Developer tools for qforge automation."""
    pass

@dev.command("sync")
def sync():
    """Update documentation tables and internal lists."""
    console.print("[bold cyan]Syncing qforge documentation...[/bold cyan]")
    
    _sync_docs_qubits()
    
    console.print("\n[bold green]✓ Sync complete![/bold green]")

def _rst_list_table(rows):
    """Render header + body rows as a reStructuredText list-table."""
    lines = [
        ".. list-table::",
        "   :header-rows: 1",
        "   :widths: 18 34 18 30",
        "",
    ]
    for row in rows:
        for i, cell in enumerate(row):
            prefix = "   * - " if i == 0 else "     - "
            lines.append(f"{prefix}{cell}")
    return "\n".join(lines) + "\n"


def _sync_docs_qubits():
    """Regenerate the qubit preset table in docs/qubits.rst from QUBIT_PRESETS."""
    target_file = Path("docs") / "qubits.rst"

    if not target_file.exists():
        console.print(f"[yellow]File {target_file} not found. Skipping.[/yellow]")
        return

    content = target_file.read_text(encoding="utf-8")

    start_marker = ".. DYNAMIC_TABLE: QUBITS"
    end_marker = ".. END_DYNAMIC_TABLE"

    if start_marker not in content or end_marker not in content:
        console.print(f"[yellow]Markers not found in {target_file}[/yellow]")
        return

    rows = [("Qubit type", "Key parameters", "Typical frequency", "Best for")]

    for q_type, data in QUBIT_PRESETS.items():
        info = data.get("_info", {})
        freq = info.get("freq", "Unknown")
        desc = info.get("best_for", "N/A")

        # Basis sizes and bias points are per-run choices, not what distinguishes
        # one architecture from another, so they stay out of the summary table.
        typical = data.get("typical", {})
        ignored = ["flux", "ng", "ng1", "ng2", "ncut", "cutoff", "grid", "truncated_dim"]
        params = [k for k in typical if k not in ignored]

        rows.append((f"**{q_type.capitalize()}**", ", ".join(params), freq, desc))

    new_table = _rst_list_table(rows)

    pre = content.split(start_marker)[0]
    post = content.split(end_marker, 1)[1]

    new_content = f"{pre}{start_marker}\n\n{new_table}\n{end_marker}{post}"
    target_file.write_text(new_content, encoding="utf-8")
    console.print(f"[green]✓ Updated Qubits table in {target_file}[/green]")
