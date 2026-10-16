import shutil
import sys
import traceback
from pathlib import Path
from typing import Annotated

import typer

from labcatalog import defaults
from labcatalog.exceptions import EXIT_ISSUES, EXIT_OK, EXIT_UNEXPECTED, LabCatalogError
from labcatalog.export import run_export
from labcatalog.freeze import RECORD_ONLY
from labcatalog.issues import Issue, has_errors, summarize_issues
from labcatalog.pipeline import (
    run_check,
    run_codebook_create,
    run_codebook_import,
    run_codebook_prompt,
    run_freeze,
    run_prepare,
    run_schema,
    run_validate,
)
from labcatalog.project import init_project

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
            "--example/--no-example",
            help="Start from the fictional example project instead of empty settings.",
        ),
    ] = True,
) -> None:
    """Create a new project folder."""
    root = init_project(target, example)
    typer.echo(f"Created {root}. Open it with: labcatalog gui -p {root}")


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
def prepare(project: ProjectOption = Path(".")) -> None:
    """Run the prepare steps in labcatalog.yaml in order, stopping at the first failure."""
    runs = run_prepare(project, typer.echo)
    if not runs:
        typer.echo(f"No prepare steps in {defaults.CONFIG_FILENAME}.")
    elif runs[-1].exit_code != 0:
        typer.echo(f"Step {runs[-1].name} {runs[-1].outcome}.", err=True)
        raise typer.Exit(EXIT_ISSUES)
    else:
        typer.echo(f"{len(runs)} step(s) succeeded.")


@app.command()
def freeze(
    name: Annotated[
        str, typer.Argument(help="Name of the freeze, for example 2026-06-submission.")
    ],
    project: ProjectOption = Path("."),
) -> None:
    """Record the data as they are now; DataLad datasets are also saved and tagged."""
    path, record = run_freeze(project, name, shutil.which("datalad"))
    typer.echo(f"Wrote {path}")
    if record.tag:
        typer.echo(f"Tagged {record.tag} in {len(record.manifest.datalad)} DataLad dataset(s).")
    else:
        typer.echo(RECORD_ONLY)


codebook_app = typer.Typer(
    help="Import the codebook of a data file that has no column map yet.", no_args_is_help=True
)
app.add_typer(codebook_app, name="codebook")
DatasetArgument = Annotated[str, typer.Argument(help="Dataset name from labcatalog.yaml.")]


@codebook_app.command("create")
def codebook_create(
    dataset: DatasetArgument,
    redcap: Annotated[
        Path | None,
        typer.Option(
            "--redcap", help="REDCap data dictionary to take wording, options and item types from."
        ),
    ] = None,
    qualtrics: Annotated[
        Path | None,
        typer.Option("--qualtrics", help="Qualtrics survey file (.qsf) to take the same from."),
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Write three CSV files that list every column of the data file, to fill in."""
    for path in run_codebook_create(project, dataset, redcap or qualtrics):
        typer.echo(f"Wrote {path}")
    typer.echo(f"Fill them in, then run: labcatalog codebook import {dataset}")


@codebook_app.command("prompt")
def codebook_prompt(dataset: DatasetArgument, project: ProjectOption = Path(".")) -> None:
    """Print a prompt that asks an AI to fill in the three files from your codebook."""
    typer.echo(run_codebook_prompt(project, dataset))


@codebook_app.command("import")
def codebook_import(dataset: DatasetArgument, project: ProjectOption = Path(".")) -> None:
    """Check the three files, then write the instrument files and the column map."""
    result = run_codebook_import(project, dataset)
    print_issues(result.issues)
    for path in result.written:
        typer.echo(f"Wrote {path}")
    if result.reused:
        typer.echo(f"Already in the project, so only mapped: {', '.join(result.reused)}")
    for instruction, lines in result.steps:
        typer.echo(instruction)
        typer.echo(lines)
    raise typer.Exit(EXIT_ISSUES if has_errors(result.issues) else EXIT_OK)


@app.command()
def export(
    instruments: Annotated[list[str], typer.Argument(help="IDs of the instruments to export.")],
    dataset: Annotated[
        list[str] | None,
        typer.Option(
            "--dataset", "-d", help="Only this dataset; repeat for more. Default: every dataset."
        ),
    ] = None,
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Folder to create the export folder in.")
    ] = Path("."),
    project: ProjectOption = Path("."),
) -> None:
    """Write a variable list and each dataset's data for the chosen instruments."""
    typer.echo(f"Wrote {run_export(project, instruments, dataset or [], out)}")


@app.command()
def schema(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Folder to write the JSON Schema files to.")
    ] = Path(defaults.SCHEMAS_DIR),
) -> None:
    """Write JSON Schema files so editors can autocomplete and check the YAML."""
    for path in run_schema(out):
        typer.echo(f"Wrote {path}")
