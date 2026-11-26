"""
CLI commands for managing QubitWeave internal caches.
"""

import click
import os
from rich.console import Console
from QubitWeave.config.defaults import OUTPUT_DIRS

console = Console()

@click.group(name="cache")
def cache_group():
    """Manage QubitWeave internal caches (calibrations, compiled circuits)."""
    pass

@cache_group.command(name="clear")
def clear():
    """Clear the physical gate calibration cache."""
    # This must match the exact path logic in your GateEngine.__init__
    cache_file = os.path.join(OUTPUT_DIRS.get("data", "outputs"), "calib_cache.json")
    
    parametric_file = os.path.join(os.path.dirname(cache_file), "parametric_cache.json")
    if os.path.exists(parametric_file):
        os.remove(parametric_file)

    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            console.print("[bold green]✓ Successfully cleared calibration cache.[/bold green]")
            console.print(f"[dim](Removed: {cache_file})[/dim]")
            
            # Note: We don't need to clear the GateEngine._calib_cache RAM dictionary
            # here because CLI commands spin up fresh Python processes anyway!
            
        except Exception as e:
            console.print(f"[bold red]Error clearing cache: {e}[/bold red]")
    else:
        console.print("[yellow]Cache is already empty (No calibration file found).[/yellow]")