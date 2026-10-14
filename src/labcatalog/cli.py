import sys
import traceback
from pathlib import Path
from typing import Annotated

import typer

from labcatalog.exceptions import EXIT_ISSUES, EXIT_OK, EXIT_UNEXPECTED, LabCatalogError
from labcatalog.issues import Issue, has_errors, summarize_issues
from labcatalog.pipeline import run_check, run_validate

app = typer.Typer(
    help="Build a browsable catalog of a lab's study data.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectOption = Annotated[
    Path, typer.Option("--project", "-p", help="Project folder containing labcatalog.yaml.")
]


def main() -> None:
    try:
        app()
    except LabCatalogError as err:
        typer.echo(f"Error: {err}", err=True)
        sys.exit(err.exit_code)
    except Exception:
        traceback.print_exc()
        sys.exit(EXIT_UNEXPECTED)


def print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        prefix = f"{issue.location}: " if issue.location else ""
        typer.echo(f"{prefix}{issue.level} [{issue.code}] {issue.message}")
    typer.echo(summarize_issues(issues))


@app.command()
def gui(
    project: Annotated[
        Path | None,
        typer.Option("--project", "-p", help="Project folder to open when the window starts."),
    ] = None,
) -> None:
    """Open the labcatalog window."""
    # Imported here so other commands do not pay for loading the GUI stack.
    from labcatalog.gui import launch

    launch(project)


@app.command()
def init(
    target: Annotated[Path, typer.Argument(help="Folder to create the project in.")],
    example: Annotated[
        bool,
        typer.Option(
            "--example/--no-example", help="Include an example instrument, study, and data."
        ),
    ] = True,
) -> None:
    """Create a new project folder."""
    raise NotImplementedError


@app.command()
def validate(project: ProjectOption = Path(".")) -> None:
    """Check the metadata and configuration without reading data."""
    issues = run_validate(project)
    print_issues(issues)
    raise typer.Exit(EXIT_ISSUES if has_errors(issues) else EXIT_OK)


@app.command()
def check(project: ProjectOption = Path(".")) -> None:
    """Read the data and report mismatches with the metadata."""
    report = run_check(project)
    print_issues(report.issues)
    raise typer.Exit(EXIT_ISSUES if report.has_errors() else EXIT_OK)


@app.command()
def schema(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Folder to write the JSON Schema files to.")
    ] = Path("schemas"),
) -> None:
    """Write JSON Schema files so editors can autocomplete and check the YAML."""
    raise NotImplementedError
