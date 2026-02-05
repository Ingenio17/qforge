"""
Cleanup CLI command for QForge.
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
@click.option("--days", type=int, default=None, help="Delete runs older than N days")
def clean(force, dry_run, days):
    """
    Clean up simulation outputs and logs.
    
    Removes the contents of the outputs/runs directory.
    """
    runs_dir = Path(OUTPUT_DIRS["base"]) / "runs"
    
    if not runs_dir.exists():
        console.print("[yellow]No runs directory found. Nothing to clean.[/yellow]")
        return

    # Collect items to delete
    items_to_delete = []
    total_size = 0
    
    import time
    current_time = time.time()
    
    for item in runs_dir.iterdir():
        if days is not None:
            # Check modification time
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
