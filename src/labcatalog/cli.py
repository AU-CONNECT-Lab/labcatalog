from pathlib import Path
from typing import Annotated

import typer

from labcatalog import defaults

app = typer.Typer(
    help="Build a browsable catalog of a lab's study data.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectOption = Annotated[
    Path, typer.Option("--project", "-p", help="Project folder containing labcatalog.yaml.")
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON to stdout.")]


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
def validate(project: ProjectOption = Path("."), json_output: JsonOption = False) -> None:
    """Check the metadata and configuration without reading data."""
    raise NotImplementedError


@app.command()
def check(project: ProjectOption = Path("."), json_output: JsonOption = False) -> None:
    """Read the data and report mismatches with the metadata."""
    raise NotImplementedError


@app.command()
def build(
    project: ProjectOption = Path("."),
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", "-o", help="Output folder; defaults to output.dir in labcatalog.yaml."
        ),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Build the internal catalog website."""
    raise NotImplementedError


@app.command()
def preview(
    project: ProjectOption = Path("."),
    port: Annotated[
        int, typer.Option("--port", help="Local port to serve on.")
    ] = defaults.PREVIEW_PORT,
) -> None:
    """Serve the built website locally, including linked reference PDFs."""
    raise NotImplementedError


@app.command()
def schema(
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Folder to write the JSON Schema files to.")
    ] = Path("schemas"),
) -> None:
    """Write JSON Schema files so editors can autocomplete and check the YAML."""
    raise NotImplementedError
