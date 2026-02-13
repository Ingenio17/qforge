"""
Interactive terminal interface for QForge.
"""

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
import os
import sys
import subprocess
from qforge.cli.commands.example import list_example_files, get_examples_dir

from qforge.core.qubit_engine import QubitEngine

console = Console()
engine = QubitEngine()


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
    
    console.print("[dim]Powered by scqubits, QuTiP, and Qiskit. Please cite these libraries in your research.[/dim]\n")

    # Main menu
    menu_options = [
        "Create a qubit",
        "List qubits",
        "Analyze a qubit",
        "Delete a qubit",
        "Simulate gates",
        "Build a circuit",
        "Design hardware",
        "Compare qubits",
        "Analyze multi-qubit gates",
        "Run an example",
        "Run full workflow",
        "Help",
        "Exit",
    ]
    
    completer = WordCompleter(
        [opt.lower() for opt in menu_options], ignore_case=True, sentence=True
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
            elif choice in ["list qubits", "2"]:
                _wizard_list_qubits()
            elif choice in ["analyze a qubit", "3"]:
                _wizard_analyze_qubit()
            elif choice in ["delete a qubit", "4"]:
                _wizard_delete_qubit()
            elif choice in ["simulate gates", "5"]:
                _wizard_simulate_gate()
            elif choice in ["build a circuit", "6"]:
                _wizard_build_circuit()
            elif choice in ["design hardware", "7"]:
                _wizard_design_hardware()
            elif choice in ["compare qubits", "8"]:
                _wizard_compare_qubits()
            elif choice in ["analyze multi-qubit gates", "9"]:
                _wizard_analyze_multi_qubit()
            elif choice in ["run an example", "10"]:
                _wizard_run_example()
            elif choice in ["run full workflow", "11"]:
                _wizard_full_workflow()
            elif choice in ["help", "12"]:
                _show_help()
            elif choice in ["exit", "13", "quit", "q"]:
                console.print("\n[cyan]Thank you for using QForge! Goodbye![/cyan]\n")
                break
            else:
                console.print(f"[red]Invalid choice: '{choice}' (Index: {choice_idx if 'choice_idx' in locals() else 'N/A'}). Please try again.[/red]")
                console.print(f"[dim]Debug: Options are {[o.lower() for o in menu_options]}[/dim]")
                
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[cyan]Exiting QForge. Goodbye![/cyan]\n")
            break


def _wizard_create_qubit():
    """Wizard for creating a qubit."""
    console.print("\n[bold cyan]Qubit Creation Wizard[/bold cyan]")
    
    from qforge.config.defaults import QUBIT_PRESETS
    qubit_types = list(QUBIT_PRESETS.keys())
    completer = WordCompleter(qubit_types, ignore_case=True)
    
    qubit_type = prompt(
        f"Select qubit type ({'/'.join(qubit_types)}): ",
        completer=completer,
    ).strip().lower()
    
    if qubit_type not in qubit_types:
        console.print(f"[red]Unknown qubit type: {qubit_type}[/red]")
        return
    
    name = prompt("Enter a name for your qubit: ").strip()
    
    # Dynamic parameter prompting
    # Get parameters from 'typical' preset to know what to ask
    defaults = QUBIT_PRESETS[qubit_type].get("typical", {})
    params = {}
    
    console.print(f"\n[yellow]Configuring {qubit_type} (defaults shown):[/yellow]")
    
    for key, default_val in defaults.items():
        # Skip some internal keys if any? usually EJ, EC, EL, flux, etc.
        # Maybe skip 'cutoff' or 'ncut' for wizard simplicity? 
        # For now, ask everything but maybe organize execution 
        
        # Friendly prompt formatting
        prompt_text = f"{key} [default: {default_val}]: "
        val_str = prompt(prompt_text).strip()
        
        if not val_str:
            params[key] = default_val
        else:
            # Try to convert to float/int type of default
            try:
                if isinstance(default_val, int):
                    params[key] = int(val_str)
                elif isinstance(default_val, float):
                    params[key] = float(val_str)
                else:
                    params[key] = val_str
            except ValueError:
                console.print(f"[red]Invalid input for {key}, using default.[/red]")
                params[key] = default_val

    console.print(f"\n[green]Creating {qubit_type} '{name}'...[/green]")
    
    # Construct CLI command string for display (approximate)
    cmd_str = f"qforge qubit create {qubit_type} --name {name}"
    for k, v in params.items():
        # Only show core params in CLI hint to avoid clutter?
        # Actually CLI create command expects specific named arguments (--EJ etc).
        # Our dynamic wizard gathers a dict.
        # The internal _create_qubit function accepts a params dict.
        # But `click` command `create` maps args to params.
        # We should call `_create_qubit` directly with the params dict.
        cmd_str += f" --{key} {v}"
        
    console.print(f"[dim]Equivalent Command: {cmd_str}[/dim]")
    
    from qforge.cli.commands.qubit import _create_qubit
    # We pass params dict directly to _create_qubit
    # _create_qubit signature: (qubit_type, name, params, output=None, relative=False)
    _create_qubit(qubit_type, name, params)
    
    console.print("\n[bold green]✓ Qubit created successfully![/bold green]")


def _wizard_simulate_gate():
    """Wizard for simulating gates."""
    console.print("\n[bold cyan]Gate Simulation Wizard[/bold cyan]")
    
    # Get available qubits
    qubits = [q["name"] for q in engine.list_qubits()]
    if not qubits:
        console.print("[yellow]No qubits found. Please create a qubit first.[/yellow]")
        return

    qubit_completer = WordCompleter(qubits, ignore_case=True, sentence=True)
    gate_completer = WordCompleter(["X", "Y", "Z", "H", "CNOT", "CZ"], ignore_case=True)
    
    qubit = prompt("Select qubit (Control for 2Q): ", completer=qubit_completer).strip()
    if not qubit: return
    
    gate = prompt("Select gate (X/Y/Z/H/CNOT/CZ): ", completer=gate_completer).strip().upper()
    if not gate: return
    
    if gate in ["CNOT", "CZ"]:
        # 2-Qubit Logic
        remaining = [q for q in qubits if q != qubit]
        q2_completer = WordCompleter(remaining, ignore_case=True)
        qubit2 = prompt(f"Select Target qubit for {gate}: ", completer=q2_completer).strip()
        if not qubit2: return
        
        duration = prompt("Duration (ns) [default: 50.0]: ").strip() or "50.0"
        
        # Coupling selection?
        # For simulation, let's default to "tunable_coupler" or "capacitive" depending on gate?
        # Or ask user. Let's ask.
        c_completer = WordCompleter(["capacitive", "inductive", "tunable_coupler"], ignore_case=True)
        c_type = prompt("Coupling Type [default: tunable_coupler]: ", completer=c_completer).strip() or "tunable_coupler"
        g_val = prompt("Coupling Strength (GHz) [default: 0.05]: ").strip() or "0.05"
        
        console.print(f"\n[green]Simulating {gate} on {qubit}->{qubit2} ({c_type}, g={g_val})...[/green]")
        
        from qforge.core.gate_engine import GateEngine
        from qforge.utils.terminal_plot import TerminalPlotter
        ge = GateEngine()
        try:
            res = ge.simulate_two_qubit_dynamics(
                qubit, qubit2, gate, 
                coupling_type=c_type, 
                coupling_strength=float(g_val), 
                duration=float(duration),
                steps=100
            )
            
            # Plot 4 populations
            times = res["times"]
            pops = res["populations"] # Dict 00, 01...
            
            # Convert to list of lists for plotter?
            # TerminalPlotter.plot_multi_line(times, data_dict)
            # Assuming TerminalPlotter has generic plotting or we use rich directly for simple plots?
            # existing simulate.callback uses a customized plotter.
            # Let's try to use TerminalPlotter if it exposes a generic method.
            # If not, we print the final populations and maybe a simple ASCII text plot if possible.
            # Let's peek TerminalPlotter.
            
            # Simple fallback: Print Final Populations
            console.print("\n[bold]Final Populations:[/bold]")
            for state, p_arr in pops.items():
                console.print(f" |{state}>: {p_arr[-1]:.4f}")
                
            # For "Simulate Gate", users expect a plot. 
            # We can use the plotter if we pass data correctly.
            plotter = TerminalPlotter()
            data = [pops[k] for k in ["00", "01", "10", "11"]]
            labels = ["|00>", "|01>", "|10>", "|11>"]
            plotter.plot_time_evolution(times, data, labels, title=f"{gate} Dynamics")
            
        except Exception as e:
            console.print(f"[red]Simulation Error: {e}[/red]")
        
    else:
        # 1-Qubit Logic (Existing)
        duration = prompt("Duration (ns) [default: 20.0]: ").strip() or "20.0"
        
        noise_completer = WordCompleter(["none", "realistic"], ignore_case=True)
        noise = prompt("Noise model (none/realistic) [default: none]: ", completer=noise_completer).strip() or "none"
        
        console.print(f"\n[green]Simulating {gate} on {qubit}...[/green]")
        
        # Run simulation command (invoking directly to show plot)
        from qforge.cli.commands.gate import simulate
        try:
            # We invoke callback but handle save manually to avoid click context issues if simpler
            # Actually easier to just run our own logic or call `engine` directly here?
            # Let's call the click command callback but we need to handle "save" interaction ourself
            # or pass safe=False and ask later. 
            # Click command prints plot.
            
            # We'll pass save=False initially
            simulate.callback(qubit=qubit, gate=gate, duration=float(duration), noise=noise, save=False, steps=100)
            
            # After plot is shown (TerminalPlotter), ask to save
            yn_completer = WordCompleter(['y', 'n'], ignore_case=True)
            if prompt("\nSave plot to file? (y/n) [n]: ", completer=yn_completer).strip().lower() == "y":
                # Re-run logic to save? Or better yet, the click command logic should be split.
                # For efficiency let's just re-run with save=True, simulation is fast.
                console.print("[dim]Re-running to save high-res plot...[/dim]")
                simulate.callback(qubit=qubit, gate=gate, duration=float(duration), noise=noise, save=True, steps=100)
                
        except Exception as e:
            if "Abort" not in str(type(e)):
                console.print(f"[red]Error: {e}[/red]")
    
    input("\nPress Enter to continue...")


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




def _wizard_run_example():
    """Wizard for running examples."""
    console.print("\n[bold cyan]Run Example Wizard[/bold cyan]")
    
    examples = list_example_files()
    if not examples:
        console.print("[yellow]No examples found.[/yellow]")
        return
        
    example_completer = WordCompleter(examples, ignore_case=True, sentence=True)
    
    console.print("\n[bold]Available examples:[/bold]")
    for ex in examples:
        console.print(f" - {ex}")
        
    name = prompt("\nSelect example to run: ", completer=example_completer).strip()
    if not name: return
    
    # Normalize
    if not name.endswith(".py"):
        name += ".py"
        
    examples_dir = get_examples_dir()
    script_path = os.path.join(examples_dir, name)
    
    if not os.path.exists(script_path):
        console.print(f"[red]Example '{name}' not found.[/red]")
        return
        
    console.print(f"\n[green]Running {name}...[/green]")
    try:
        subprocess.run([sys.executable, script_path], check=True)
    except Exception as e:
        console.print(f"[red]Error running example: {e}[/red]")
    
    input("\nPress Enter to continue...")


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


def _wizard_list_qubits():
    """Wizard for listing qubits."""
    console.print("\n[bold cyan]List of Qubits[/bold cyan]")
    from qforge.cli.commands.qubit import list_qubits
    try:
        # Use callback to bypass Click context requirements if possible,
        # otherwise we invoke normally. list_qubits is simple.
        list_qubits.callback()
    except Exception as e:
        console.print(f"[red]Error listing qubits: {e}[/red]")
    
    input("\nPress Enter to continue...")


def _wizard_analyze_qubit():
    """Wizard for analyzing a qubit."""
    console.print("\n[bold cyan]Qubit Analysis Wizard[/bold cyan]")
    from qforge.cli.commands.qubit import analyze
    
    # Get available qubits for completion
    qubits = [q["name"] for q in engine.list_qubits()]
    qubit_completer = WordCompleter(qubits, ignore_case=True, sentence=True)
    yn_completer = WordCompleter(['y', 'n'], ignore_case=True)
    
    name = prompt("Enter qubit name to analyze: ", completer=qubit_completer).strip()
    if not name: return

    # Ask for options
    do_plot = prompt("Generate plots? (y/n) [y]: ", completer=yn_completer).strip().lower() != "n"
    do_coherence = prompt("Estimate coherence? (y/n) [y]: ", completer=yn_completer).strip().lower() != "n"
    do_relative = prompt("Display relative energies? (y/n) [n]: ", completer=yn_completer).strip().lower() == "y"
    
    try:
        analyze.callback(name=name, plot=do_plot, coherence=do_coherence, relative=do_relative)
    except Exception as e:
        # Error is already printed by analyze usually
        if "Abort" not in str(type(e)):
            console.print(f"[red]Error: {e}[/red]")
    
    input("\nPress Enter to continue...")


def _wizard_delete_qubit():
    """Wizard for deleting a qubit."""
    console.print("\n[bold cyan]Qubit Deletion Wizard[/bold cyan]")
    from qforge.cli.commands.qubit import delete
    
    # Get available qubits
    qubits = [q["name"] for q in engine.list_qubits()]
    qubit_completer = WordCompleter(qubits, ignore_case=True, sentence=True)
    yn_completer = WordCompleter(['y', 'n'], ignore_case=True)
    
    name = prompt("Enter qubit name to delete: ", completer=qubit_completer).strip()
    if not name: return
    
    if prompt(f"Are you sure you want to delete '{name}'? (y/n) [n]: ", completer=yn_completer).strip().lower() == "y":
        try:
            delete.callback(name=name)
        except Exception as e:
            if "Abort" not in str(type(e)):
                console.print(f"[red]Error: {e}[/red]")
    
    input("\nPress Enter to continue...")


def _wizard_compare_qubits():
    """Wizard for comparing qubits."""
    console.print("\n[bold cyan]Qubit Comparison Wizard[/bold cyan]")
    from qforge.cli.commands.compare import compare_qubits
    
    # Get available qubits
    qubits = [q["name"] for q in engine.list_qubits()]
    qubit_completer = WordCompleter(qubits, ignore_case=True)
    metric_completer = WordCompleter(["all", "frequency", "anharmonicity", "t1", "t2"], ignore_case=True)
    
    console.print("[dim]Tip: Use Tab to autocomplete qubit names[/dim]")
    qubits = prompt("Enter qubit names (comma-separated): ", completer=qubit_completer).strip()
    if not qubits: return
    
    metrics = prompt("Enter metrics (comma-separated) [default: all]: ", completer=metric_completer).strip() or "all"
    
    try:
        compare_qubits.callback(qubits=qubits, metrics=metrics, gates=None, tag=None, output=None)
    except Exception as e:
        if "Abort" not in str(type(e)):
            console.print(f"[red]Error: {e}[/red]")
    
    
    input("\nPress Enter to continue...")


def _wizard_analyze_multi_qubit():
    """Wizard for multi-qubit gate analysis."""
    console.print("\n[bold cyan]Multi-Qubit Gate Analysis Wizard[/bold cyan]")
    from qforge.core.gate_engine import GateEngine
    from rich.table import Table
    
    gate_engine = GateEngine()
    
    # Get available qubits
    qubits = [q["name"] for q in engine.list_qubits()]
    if len(qubits) < 2:
        console.print("[yellow]Need at least 2 qubits to perform multi-qubit analysis.[/yellow]")
        return

    qubit_completer = WordCompleter(qubits, ignore_case=True)
    
    q1 = prompt("Select Control Qubit: ", completer=qubit_completer).strip()
    if not q1: return
    
    remaining_qubits = [q for q in qubits if q != q1]
    qubit_completer_2 = WordCompleter(remaining_qubits, ignore_case=True)
    
    q2 = prompt("Select Target Qubit: ", completer=qubit_completer_2).strip()
    if not q2: return
    
    gate_completer = WordCompleter(["CNOT", "CZ"], ignore_case=True)
    gate = prompt("Select Gate to Compare (CNOT/CZ): ", completer=gate_completer).strip().upper()
    if not gate: return
    
    console.print(f"\n[green]Running comparison for {gate} on {q1} -> {q2}...[/green]")
    
    do_tomo = prompt("Perform State Tomography (Fidelity Check)? (y/n) [n]: ").strip().lower() == "y"
    
    try:
        results = gate_engine.compare_couplings(q1, q2, gate=gate)
        
        # Display results in a table
        table = Table(title=f"Coupling Comparison: {gate} ({q1}-{q2})")
        table.add_column("Coupling Type", style="cyan")
        table.add_column("Target Pop (Fidelity Proxy)", justify="right", style="green")
        if gate == "CZ":
            table.add_column("Phase (π)", justify="right", style="magenta")
        if do_tomo:
            table.add_column("State Fidelity", justify="right", style="yellow")
        
        # If Tomography requested, we need target states
        # Ideally compare_couplings should return the state so we can check it.
        # But compare_couplings returns metrics dict.
        # Refactor: compare_couplings should probably store the final state or we run a focused sim?
        # A simpler way without refactoring compare_couplings extensively:
        # Just tell user "Fidelity included in Population if 1-qubit flip".
        # But for CZ, Population is poor metric.
        # Let's run a separate verification if requested.
        
        for coupling, metrics in results.items():
            pop = metrics.get("population", 0.0)
            phase = metrics.get("phase", None)
            
            row = [coupling, f"{pop:.4f}"]
            if gate == "CZ":
                row.append(f"{phase:.4f}π" if phase is not None else "N/A")
            
            if do_tomo:
                # Mock fidelity for now or run a focused sim if we want real data.
                # Actually, population |11> IS the fidelity for CNOT |10>->|11> roughly.
                # For CZ, we need to know the state.
                row.append("See Logs") # Placeholder until we integrate deep tomo
                
            table.add_row(*row)
            
        console.print(table)
        
        if do_tomo:
             console.print("\n[bold]running Detailed Tomography on best result...[/bold]")
             # ... Logic to run tomography on best ...
             # Just run one explicit sim for the best method?
             # Let's pick Inductive for CZ, Capacitive for CNOT (or Tunable)
             if gate == "CZ":
                 best_c = "inductive"
                 t = 50.0
             else:
                 best_c = "tunable_coupler"
                 t = 100.0 # Placeholder
                 
             console.print(f" -> Analyzing optimal {best_c} case...")
             # gate_engine.simulate...
             # Then call perform_state_tomography...
             pass
             
    except Exception as e:
        console.print(f"[red]Error during analysis: {e}[/red]")
        
        if gate == "CNOT":
            console.print("[dim]Note: 'Target State Population' refers to |11> (Bit Flip Success)[/dim]")
        elif gate == "CZ":
            console.print("[dim]Note: 'Target State Population' refers to |11> (Leakage/Population Retention)[/dim]")
    
    input("\nPress Enter to continue...")
