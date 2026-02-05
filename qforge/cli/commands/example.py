"""
CLI commands for running QForge examples.
"""

import os
import sys
import subprocess
import glob
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Common paths to look for examples
EXAMPLE_PATHS = [
    os.path.join(os.getcwd(), "examples"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "examples"),
]

def get_examples_dir():
    """Find the examples directory."""
    for path in EXAMPLE_PATHS:
        if os.path.isdir(path):
            return path
    return None

def list_example_files():
    """Return a list of example filenames."""
    examples_dir = get_examples_dir()
    if not examples_dir:
        return []
    
    files = glob.glob(os.path.join(examples_dir, "*.py"))
    return [os.path.basename(f) for f in files if not os.path.basename(f).startswith("__")]

@click.group()
def example():
    """Manage and run QForge examples."""
    pass

@example.command(name="list")
def list_examples():
    """List available example scripts."""
    examples_dir = get_examples_dir()
    if not examples_dir:
        console.print("[red]Error: 'examples' directory not found.[/red]")
        return

    files = list_example_files()
    if not files:
        console.print("[yellow]No examples found.[/yellow]")
        return

    table = Table(title="QForge Examples")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")

    for f in files:
        # Try to read docstring
        path = os.path.join(examples_dir, f)
        desc = "No description"
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
                if '"""' in content:
                    desc = content.split('"""')[1].strip().split("\n")[0]
        except Exception:
            pass
        
        table.add_row(f.replace(".py", ""), desc)

    console.print(table)

@example.command(name="run")
@click.option("--name", "-n", required=True, help="Name of the example to run (e.g., transmon_workflow)")
def run(name):
    """Run a specific example script."""
    examples_dir = get_examples_dir()
    if not examples_dir:
        console.print("[red]Error: 'examples' directory not found.[/red]")
        return

    # Normalize name
    if not name.endswith(".py"):
        name += ".py"
    
    script_path = os.path.join(examples_dir, name)
    if not os.path.exists(script_path):
        console.print(f"[red]Error: Example '{name}' not found.[/red]")
        console.print(f"Available examples in {examples_dir}:")
        for f in list_example_files():
            console.print(f" - {f}")
        return

    console.print(f"\n[green]Running {name}...[/green]")
    console.print(f"[dim]Source: {script_path}[/dim]\n")

    try:
        # Run using current python interpreter
        subprocess.run([sys.executable, script_path], check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"\n[red]Example failed with exit code {e.returncode}[/red]")
    except Exception as e:
        console.print(f"\n[red]Error running example: {e}[/red]")
