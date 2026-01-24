"""
Interactive terminal interface for QForge.
"""

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def run_interactive():
    """Run QForge in interactive mode with guided workflows."""
    
    console.print(
        Panel.fit(
            "[bold cyan]Welcome to QForge Interactive Mode![/bold cyan]\n\n"
            "This guided interface will help you build quantum simulations step-by-step.\n"
            "Perfect for beginners and quick prototyping.\n\n"
            "[yellow]Tip:[/yellow] Type 'help' for assistance, 'exit' to quit.",
            border_style="cyan",
        )
    )
    
    # Main menu
    menu_options = [
        "Create a qubit",
        "Simulate gates",
        "Build a circuit",
        "Design hardware",
        "Compare qubits",
        "Run full workflow",
        "Help",
        "Exit",
    ]
    
    completer = WordCompleter(
        [opt.lower() for opt in menu_options], ignore_case=True
    )
    
    while True:
        console.print("\n[bold]What would you like to do?[/bold]")
        for idx, option in enumerate(menu_options, 1):
            console.print(f"  {idx}. {option}")
        
        try:
            choice = prompt(
                "\n> Your choice (number or name): ",
                completer=completer,
            ).strip()
            
            # Handle numeric or text input
            if choice.isdigit():
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(menu_options):
                    choice = menu_options[choice_idx].lower()
                else:
                    console.print("[red]Invalid choice. Please try again.[/red]")
                    continue
            else:
                choice = choice.lower()
            
            # Route to appropriate wizard
            if choice in ["create a qubit", "1"]:
                _wizard_create_qubit()
            elif choice in ["simulate gates", "2"]:
                _wizard_simulate_gate()
            elif choice in ["build a circuit", "3"]:
                _wizard_build_circuit()
            elif choice in ["design hardware", "4"]:
                _wizard_design_hardware()
            elif choice in ["compare qubits", "5"]:
                _wizard_compare_qubits()
            elif choice in ["run full workflow", "6"]:
                _wizard_full_workflow()
            elif choice in ["help", "7"]:
                _show_help()
            elif choice in ["exit", "8", "quit", "q"]:
                console.print("\n[cyan]Thank you for using QForge! Goodbye![/cyan]\n")
                break
            else:
                console.print("[red]Invalid choice. Please try again.[/red]")
                
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[cyan]Exiting QForge. Goodbye![/cyan]\n")
            break


def _wizard_create_qubit():
    """Wizard for creating a qubit."""
    console.print("\n[bold cyan]Qubit Creation Wizard[/bold cyan]")
    
    qubit_types = ["transmon", "fluxonium", "flux", "zeropi"]
    completer = WordCompleter(qubit_types, ignore_case=True)
    
    qubit_type = prompt(
        "Select qubit type (transmon/fluxonium/flux/zeropi): ",
        completer=completer,
    ).strip().lower()
    
    if qubit_type not in qubit_types:
        console.print(f"[red]Unknown qubit type: {qubit_type}[/red]")
        return
    
    name = prompt("Enter a name for your qubit: ").strip()
    
    if qubit_type == "transmon":
        console.print("\n[yellow]Transmon requires: EJ (Josephson energy) and EC (charging energy)[/yellow]")
        ej = prompt("EJ (GHz) [default: 15]: ").strip() or "15"
        ec = prompt("EC (GHz) [default: 0.3]: ").strip() or "0.3"
        
        console.print(f"\n[green]Creating transmon '{name}' with EJ={ej} GHz, EC={ec} GHz...[/green]")
        console.print(f"[dim]Command: qforge qubit create transmon --name {name} --EJ {ej} --EC {ec}[/dim]")
        
        # Import and execute
        from qforge.cli.commands.qubit import _create_qubit
        _create_qubit(qubit_type, name, {"EJ": float(ej), "EC": float(ec)})
        
    elif qubit_type == "fluxonium":
        console.print("\n[yellow]Fluxonium requires: EJ, EC, and EL (inductive energy)[/yellow]")
        ej = prompt("EJ (GHz) [default: 8.9]: ").strip() or "8.9"
        ec = prompt("EC (GHz) [default: 2.5]: ").strip() or "2.5"
        el = prompt("EL (GHz) [default: 0.5]: ").strip() or "0.5"
        
        console.print(f"\n[green]Creating fluxonium '{name}' with EJ={ej} GHz, EC={ec} GHz, EL={el} GHz...[/green]")
        console.print(f"[dim]Command: qforge qubit create fluxonium --name {name} --EJ {ej} --EC {ec} --EL {el}[/dim]")
        
        from qforge.cli.commands.qubit import _create_qubit
        _create_qubit(qubit_type, name, {"EJ": float(ej), "EC": float(ec), "EL": float(el)})
    
    console.print("\n[bold green]✓ Qubit created successfully![/bold green]")


def _wizard_simulate_gate():
    """Wizard for simulating gates."""
    console.print("\n[bold cyan]Gate Simulation Wizard[/bold cyan]")
    console.print("[yellow]This feature will simulate quantum gate dynamics with realistic noise.[/yellow]")
    console.print("[dim]Coming soon in interactive mode. Use: qforge gate simulate --help[/dim]")


def _wizard_build_circuit():
    """Wizard for building circuits."""
    console.print("\n[bold cyan]Circuit Building Wizard[/bold cyan]")
    console.print("[yellow]This feature will help you construct and simulate quantum circuits.[/yellow]")
    console.print("[dim]Coming soon in interactive mode. Use: qforge circuit build --help[/dim]")


def _wizard_design_hardware():
    """Wizard for hardware design."""
    console.print("\n[bold cyan]Hardware Design Wizard[/bold cyan]")
    console.print("[yellow]This feature will help you design quantum chip layouts.[/yellow]")
    console.print("[dim]Coming soon in interactive mode. Use: qforge hardware design --help[/dim]")


def _wizard_compare_qubits():
    """Wizard for comparing qubits."""
    console.print("\n[bold cyan]Qubit Comparison Wizard[/bold cyan]")
    console.print("[yellow]This feature will compare different qubit architectures side-by-side.[/yellow]")
    console.print("[dim]Coming soon in interactive mode. Use: qforge compare --help[/dim]")


def _wizard_full_workflow():
    """Wizard for full workflow."""
    console.print("\n[bold cyan]Full Workflow Wizard[/bold cyan]")
    console.print("[yellow]This will guide you through: qubit → gate → circuit → hardware.[/yellow]")
    console.print("[dim]Coming soon in interactive mode. Use: qforge workflow run --help[/dim]")


def _show_help():
    """Show help information."""
    help_md = """
# QForge Interactive Mode Help

## Navigation
- Use **number keys** or **type the option name** to select
- Type **exit** or press **Ctrl+C** to quit
- Tab completion is available for most inputs

## Workflow Stages

1. **Create a Qubit**: Define physical parameters of superconducting qubits
2. **Simulate Gates**: Model gate dynamics with realistic noise
3. **Build a Circuit**: Construct multi-qubit circuits
4. **Design Hardware**: Layout quantum chip geometry
5. **Compare Qubits**: Side-by-side analysis of different architectures
6. **Run Full Workflow**: End-to-end simulation pipeline

## Tips
- Start with creating a qubit if you're new
- Use default values for quick testing
- Check the documentation at: qforge --help
    """
    
    console.print(Panel(Markdown(help_md), title="Help", border_style="yellow"))
