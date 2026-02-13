"""
Developer CLI commands for QForge.
"""

import click
from rich.console import Console
from pathlib import Path
from qforge.config.defaults import QUBIT_PRESETS

console = Console()

@click.group()
def dev():
    """Developer tools for QForge automation."""
    pass

@dev.command("sync")
def sync():
    """Update documentation tables and internal lists."""
    console.print("[bold cyan]Syncing QForge documentation...[/bold cyan]")
    
    _sync_docs_qubits()
    
    console.print("\n[bold green]✓ Sync complete![/bold green]")

def _sync_docs_qubits():
    """Update Qubits table in docs/getting_started.md"""
    docs_dir = Path("docs")
    target_file = docs_dir / "getting_started.md"
    
    if not target_file.exists():
        console.print(f"[yellow]File {target_file} not found. Skipping.[/yellow]")
        return
        
    content = target_file.read_text(encoding="utf-8")
    
    start_marker = "<!-- DYNAMIC_TABLE: QUBITS -->"
    end_marker = "<!-- END_DYNAMIC_TABLE -->"
    
    if start_marker in content and end_marker in content:
        # Generate Table
        header = "| Qubit Type | Key Parameters | Typical Frequency | Best For |\n|------------|---------------|-------------------|----------|"
        rows = []
        
        for q_type, data in QUBIT_PRESETS.items():
            # Info
            info = data.get("_info", {})
            freq = info.get("freq", "Unknown")
            desc = info.get("best_for", "N/A")
            
            # Params (exclude standard ones for brevity)
            typical = data.get("typical", {})
            ignored = ["flux", "ng", "ncut", "cutoff", "grid"]
            params = [k for k in typical.keys() if k not in ignored]
            
            # Format
            q_name = q_type.capitalize()
            # If multiple EJs (flux), handle carefully?
            # Flux parameters: EJ1, EJ2, EJ3...
            
            params_str = ", ".join(params)
            
            rows.append(f"| **{q_name}** | {params_str} | {freq} | {desc} |")
            
        new_table = header + "\n" + "\n".join(rows) + "\n"
        
        # Replace
        parts = content.split(start_marker)
        pre = parts[0]
        post = parts[1].split(end_marker)[1]
        
        new_content = pre + start_marker + "\n" + new_table + end_marker + post
        target_file.write_text(new_content, encoding="utf-8")
        console.print(f"[green]✓ Updated Qubits table in {target_file}[/green]")
    else:
        console.print(f"[yellow]Markers not found in {target_file}[/yellow]")
