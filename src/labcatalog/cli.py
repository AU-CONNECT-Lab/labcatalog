import shutil
import sys
import traceback
from pathlib import Path
from typing import Annotated

import typer

from labcatalog import defaults
from labcatalog.codebook.derivatives import Request, run_derivatives
from labcatalog.datalad.freeze import RECORD_ONLY
from labcatalog.exceptions import (
    EXIT_ISSUES,
    EXIT_OK,
    EXIT_UNEXPECTED,
    DataladError,
    LabCatalogError,
)
from labcatalog.issues import Issue, has_errors, summarize_issues
from labcatalog.pipeline import (
    run_check,
    run_codebook_answer,
    run_codebook_create,
    run_codebook_import,
    run_codebook_prompt,
    run_freeze,
    run_get,
    run_get_missing,
    run_open_freeze,
    run_prepare,
    run_push_freeze,
    run_schema,
    run_validate,
)
from labcatalog.project import init_project
from labcatalog.reports.database import run_database
from labcatalog.reports.export import BY_DATASET, run_export

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
    if report.accepted:
        typer.echo(
            f"{len(report.accepted)} warning(s) accepted in {defaults.ACCEPTED_FILENAME} "
            "are not shown."
        )
    raise typer.Exit(EXIT_ISSUES if report.has_errors() else EXIT_OK)


@app.command()
def prepare(project: ProjectOption = Path(".")) -> None:
    """Run the prepare steps in labcatalog.yaml in order, stopping at the first failure."""
    runs = run_prepare(project, typer.echo, shutil.which("datalad"))
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
    push: Annotated[
        bool, typer.Option(help="Push the tag and the data to each DataLad dataset's sibling.")
    ] = False,
) -> None:
    """Record the data as they are now; DataLad datasets are also saved and tagged."""
    datalad = shutil.which("datalad")
    path, record = run_freeze(project, name, datalad)
    typer.echo(f"Wrote {path}")
    if not record.tag:
        typer.echo(RECORD_ONLY)
        return
    typer.echo(f"Tagged {record.tag} in {len(record.manifest.datalad)} DataLad dataset(s).")
    if push:
        pushed = run_push_freeze(project, record.name, datalad)
        typer.echo(f"Pushed {len(pushed)} dataset(s).")


@app.command()
def get(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Files or folders to get; everything the project reads when left out."),
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Get the content of files DataLad has not fetched yet in this clone."""
    datalad = datalad_on_path()
    if paths:
        run_get(paths, datalad)
    else:
        run_get_missing(project, datalad)
    typer.echo("Got the missing content.")


@app.command("open-freeze")
def open_freeze(
    name: Annotated[str, typer.Argument(help="Name of the freeze, as given to labcatalog freeze.")],
    to: Annotated[
        Path | None,
        typer.Option("--to", help="New folder for the copy; a temporary folder when left out."),
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Copy the project as it was at a freeze, with its data, into a folder of its own."""
    copy = run_open_freeze(project, name, datalad_on_path(), to)
    typer.echo(f"Opened {name} in {copy}")


def datalad_on_path() -> str:
    found = shutil.which("datalad")
    if found is None:
        raise DataladError("DataLad is not on PATH; install it first")
    return found


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
    spss: Annotated[
        Path | None,
        typer.Option("--spss", help="SPSS data file (.sav) to take its labels from."),
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Write three CSV files that list every column of the data file, to fill in."""
    for path in run_codebook_create(project, dataset, redcap or qualtrics or spss):
        typer.echo(f"Wrote {path}")
    typer.echo(f"Fill them in, then run: labcatalog codebook import {dataset}")


@codebook_app.command("prompt")
def codebook_prompt(dataset: DatasetArgument, project: ProjectOption = Path(".")) -> None:
    """Print a prompt that asks an AI to fill in the three files from your codebook."""
    typer.echo(run_codebook_prompt(project, dataset))


@codebook_app.command("answer")
def codebook_answer(
    dataset: DatasetArgument,
    answer: Annotated[
        Path | None,
        typer.Argument(
            help="File holding the AI's answer; read from standard input when left out."
        ),
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Replace the three files with the three csv code blocks of the AI's answer."""
    text = answer.read_text(encoding="utf-8") if answer else sys.stdin.read()
    for path in run_codebook_answer(project, dataset, text):
        typer.echo(f"Wrote {path}")
    typer.echo(f"Look them over, then run: labcatalog codebook import {dataset}")


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
    by: Annotated[
        str,
        typer.Option(
            "--by",
            help="dataset: one file per dataset; id or group: one wide table, a row per person "
            "or per group.",
        ),
    ] = BY_DATASET,
    project: ProjectOption = Path("."),
) -> None:
    """Write a variable list, the data and their statistics for the chosen instruments into outputs/."""
    done = run_export(project, instruments, dataset or [], by)
    typer.echo(f"Wrote {done.folder}")
    for name, n in done.left_out.items():
        typer.echo(f"Left out {n} rows of {name}: their {by} repeats in that file")


@app.command()
def derivatives(
    table: Annotated[
        Path,
        typer.Argument(help="A pipeline's table (.tsv) with a bids_name or participant_id column."),
    ],
    name: Annotated[str, typer.Option(help="Name for the instruments and datasets it makes.")],
    study: Annotated[str, typer.Option(help="Study the datasets belong to.")],
    modality: Annotated[str, typer.Option(help="Modality of the datasets, such as fnirs.")],
    reporter: Annotated[str, typer.Option(help="Reporter of the datasets, such as self.")],
    split: Annotated[
        list[str] | None,
        typer.Option(
            help="Entity whose values become separate instruments, such as task; repeat for more."
        ),
    ] = None,
    columns: Annotated[
        list[str] | None,
        typer.Option(help="Only columns matching this pattern, such as 'raw_*'; repeat for more."),
    ] = None,
    wave: Annotated[
        str | None, typer.Option(help="Wave of every row, for a table without sessions.")
    ] = None,
    label: Annotated[
        str | None, typer.Option(help="Name of the instruments; the --name when left out.")
    ] = None,
    project: ProjectOption = Path("."),
) -> None:
    """Write instruments, column maps and data files from a pipeline's table and its JSON sidecar."""
    request = Request(
        table.resolve(), name, study, modality, reporter, split or [], columns or [], wave, label
    )
    done = run_derivatives(project, request)
    for path in done.written:
        typer.echo(f"Wrote {path}")
    if done.left_out:
        typer.echo(f"Not numbers, so left out: {', '.join(done.left_out)}")
    for instruction, lines in done.steps:
        typer.echo(instruction)
        typer.echo(lines)


@app.command()
def database(project: ProjectOption = Path(".")) -> None:
    """Rebuild the project's DuckDB database from its data and metadata."""
    typer.echo(f"Wrote {run_database(project)}")


@app.command()
def schema(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Folder to write the JSON Schema files to.")
    ] = Path(defaults.SCHEMAS_DIR),
) -> None:
    """Write JSON Schema files so editors can autocomplete and check the YAML."""
    for path in run_schema(out):
        typer.echo(f"Wrote {path}")
