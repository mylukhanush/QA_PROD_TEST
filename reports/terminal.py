"""
Rich terminal report output.

Produces beautiful terminal output for test runs using the Rich library.
Includes colored tables, status icons, progress bars, and panels.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()

STATUS_ICONS = {
    "pass": "[bold green]✓[/]",
    "fail": "[bold red]✗[/]",
    "error": "[bold yellow]⚠[/]",
    "skipped": "[dim]⊘[/]",
    "running": "[bold blue]⟳[/]",
    "not_run": "[dim]—[/]",
}

STATUS_COLORS = {
    "pass": "green",
    "fail": "red",
    "error": "yellow",
    "skipped": "dim",
    "running": "blue",
}


def print_run_summary(run_data: dict):
    """
    Print a full test run summary to the terminal.

    Parameters
    ----------
    run_data : dict
        Run data including status, steps, value_captures, etc.
    """
    status = run_data.get("status", "unknown")
    icon = STATUS_ICONS.get(status, "?")
    color = STATUS_COLORS.get(status, "white")

    # Header panel
    header = Text()
    header.append(f"  {run_data.get('test_name', 'Test Run')}\n", style="bold white")
    header.append(f"  Category: ", style="dim")
    header.append(f"{run_data.get('category', 'unknown')}\n", style="white")
    header.append(f"  Site: ", style="dim")
    header.append(f"{run_data.get('site', 'unknown')}\n", style="cyan")
    header.append(f"  Status: ", style="dim")
    header.append(f"{status.upper()}", style=f"bold {color}")
    if run_data.get("duration_ms"):
        header.append(f"  ({run_data['duration_ms']}ms)", style="dim")

    console.print(Panel(header, title="[bold]Test Run Report[/]", border_style=color))

    # Steps table
    steps = run_data.get("steps", [])
    if steps:
        table = Table(
            title="Steps",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold",
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Action", style="cyan", width=20)
        table.add_column("Description", width=50)
        table.add_column("Status", width=8, justify="center")
        table.add_column("Error", style="red", width=40)

        for s in steps:
            s_status = s.get("status", "unknown")
            s_icon = STATUS_ICONS.get(s_status, "?")
            error = s.get("error_message", "") or ""
            if len(error) > 80:
                error = error[:77] + "..."
            table.add_row(
                str(s.get("step_order", "")),
                s.get("action", ""),
                s.get("description", ""),
                s_icon,
                error,
            )

        console.print(table)

    # Value captures
    captures = run_data.get("value_captures", [])
    if captures:
        cap_table = Table(
            title="Value Captures",
            box=box.ROUNDED,
            title_style="bold",
        )
        cap_table.add_column("Label", style="cyan")
        cap_table.add_column("Page", style="dim")
        cap_table.add_column("Captured", style="white")
        cap_table.add_column("Expected", style="dim")
        cap_table.add_column("Match", justify="center")

        for c in captures:
            matched = c.get("matched")
            match_icon = (
                STATUS_ICONS["pass"] if matched
                else STATUS_ICONS["fail"] if matched is False
                else "—"
            )
            cap_table.add_row(
                c.get("label", ""),
                c.get("page", ""),
                c.get("captured_value", ""),
                c.get("expected_value", "") or "—",
                match_icon,
            )

        console.print(cap_table)

    # Screenshots
    screenshots = run_data.get("screenshots", [])
    if screenshots:
        console.print("\n[bold]Screenshots:[/]")
        for ss in screenshots:
            console.print(f"  📸 {ss}")

    # Summary
    summary = run_data.get("summary", "")
    if summary:
        console.print(Panel(summary, title="[bold]Summary[/]", border_style="blue"))

    console.print()


def print_comparison_table(comparison: list):
    """Print a cross-site comparison table."""
    if not comparison:
        console.print("[dim]No comparison data available.[/]")
        return

    # Gather all unique labels
    all_labels = set()
    for site_data in comparison:
        for c in site_data.get("captures", []):
            all_labels.add(c.get("label", ""))

    table = Table(
        title="Cross-Site Comparison",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold",
    )
    table.add_column("Metric", style="cyan")
    for site_data in comparison:
        table.add_column(site_data.get("site", ""), justify="center")

    for label in sorted(all_labels):
        row = [label]
        for site_data in comparison:
            val = "—"
            for c in site_data.get("captures", []):
                if c.get("label") == label:
                    val = c.get("captured_value", "—")
                    if c.get("matched") is False:
                        val = f"[red]{val}[/]"
                    elif c.get("matched") is True:
                        val = f"[green]{val}[/]"
                    break
            row.append(val)
        table.add_row(*row)

    console.print(table)


def print_history_table(label: str, data: list):
    """Print value history for a metric."""
    table = Table(
        title=f"History: {label}",
        box=box.ROUNDED,
        title_style="bold",
    )
    table.add_column("Site", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Captured At", style="dim")

    for entry in data:
        table.add_row(
            entry.get("site", ""),
            entry.get("value", ""),
            entry.get("captured_at", ""),
        )

    console.print(table)


def print_sites_table(sites: list):
    """Print a table of all sites."""
    table = Table(title="Sites", box=box.ROUNDED, title_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("URL", style="white")
    table.add_column("Active", justify="center")

    for s in sites:
        active_icon = STATUS_ICONS["pass"] if s.get("is_active") else STATUS_ICONS["fail"]
        table.add_row(s.get("name", ""), s.get("base_url", ""), active_icon)

    console.print(table)


def print_runs_table(runs: list):
    """Print a table of test runs."""
    table = Table(title="Test Runs", box=box.ROUNDED, show_lines=True, title_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Test", width=40)
    table.add_column("Site", style="cyan", width=8)
    table.add_column("Status", width=8, justify="center")
    table.add_column("Duration", style="dim", width=10)
    table.add_column("Time", style="dim", width=20)

    for i, r in enumerate(runs, 1):
        status = r.get("status", "unknown")
        icon = STATUS_ICONS.get(status, "?")
        duration = f"{r.get('duration_ms', 0)}ms" if r.get("duration_ms") else "—"
        table.add_row(
            str(i),
            r.get("description", "")[:40],
            r.get("site", ""),
            icon,
            duration,
            r.get("started_at", ""),
        )

    console.print(table)
