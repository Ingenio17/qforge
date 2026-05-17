"""
Cleanup CLI command for qforge.
"""

import click
import shutil
import os
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm

from qforge.config.defaults import OUTPUT_DIRS

console = Console()

@click.command()
@click.option("--force", "-f", is_flag=True, help="Force deletion without confirmation")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without taking action")
@click.option("--all", "-a", "all_items", is_flag=True, help="Clean ALL outputs (qubits, gates, comparisons, session)")
@click.option("--days", type=int, default=None, help="Delete runs older than N days")
def clean(force, dry_run, all_items, days):
    """
    Clean up simulation outputs and logs.
    
    By default, removes 'outputs/runs'. 
    With --all, removes 'outputs/qubits', 'outputs/gates', 'outputs/hardware', 'outputs/comparisons', and '.qforge_session.json'.
    """
    if all_items:
        dirs_to_clean = [Path(d) for d in OUTPUT_DIRS.values() if d != "outputs"] # Avoid cleaning base if it has other stuff? Actually defaults has base="outputs".
        # Better to list them explicitly or iterate all keys except base? 
        # OUTPUT_DIRS has: base, runs, qubits, gates, circuits, hardware, comparisons, plots.
        dirs_to_clean = [Path(OUTPUT_DIRS[k]) for k in OUTPUT_DIRS if k != "base"]
        # Add session file
        session_file = Path(".qforge_session.json")
    else:
        dirs_to_clean = [Path(OUTPUT_DIRS.get("runs", "outputs/runs"))]

    items_to_delete = []
    total_size = 0
    
    import time
    current_time = time.time()

    # Process directories
    for target_dir in dirs_to_clean:
        if not target_dir.exists():
            continue
            
        for item in target_dir.iterdir():
            if days is not None:
                mtime = item.stat().st_mtime
                if (current_time - mtime) < (days * 86400):
                    continue
            
            items_to_delete.append(item)
            if item.is_file():
                total_size += item.stat().st_size
            elif item.is_dir():
                for root, _, files in os.walk(item):
                    for f in files:
                        total_size += os.path.getsize(os.path.join(root, f))

    # Process session file (only if --all and exists)
    if all_items and session_file.exists():
         items_to_delete.append(session_file)
         total_size += session_file.stat().st_size

    
    if not items_to_delete:
        console.print("[green]Directory is already clean (matching criteria).[/green]")
        return
        
    # Format size
    size_mb = total_size / (1024 * 1024)
    size_str = f"{size_mb:.2f} MB"
    
    console.print(f"\n[bold]Found {len(items_to_delete)} run(s) occupying {size_str}[/bold]")
    
    if dry_run:
        console.print("\n[dim]Dry run: The following run directories would be deleted:[/dim]")
        for item in items_to_delete:
            console.print(f" - {item.name}")
        return

    if not force:
        if not Confirm.ask(f"Are you sure you want to delete these {len(items_to_delete)} items?"):
            console.print("[yellow]Cleanup aborted.[/yellow]")
            return
    
    # Perform deletion
    deleted_count = 0
    with console.status("[red]Deleting files...[/red]"):
        for item in items_to_delete:
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                deleted_count += 1
            except Exception as e:
                console.print(f"[red]Error deleting {item.name}: {e}[/red]")
    
    console.print(f"\n[green]✓ Cleanup complete. Removed {deleted_count} items.[/green]")
