import sys
import traceback
from pathlib import Path
from typing import Annotated

import typer

from labcatalog import defaults
from labcatalog.data.check import CheckReport
from labcatalog.data.prepare import Session, run_steps, stop
from labcatalog.datalad.bridge import use_folder
from labcatalog.exceptions import EXIT_ISSUES, EXIT_OK, EXIT_UNEXPECTED, LabCatalogError
from labcatalog.issues import summarize_issues
from labcatalog.pipeline import load_validated, reported, run_catalog, run_check
from labcatalog.reports.database import write_database

app = typer.Typer(
    help="Describe a lab's instruments and data, then check, browse and analyse them in one "
    "window. With no command, labcatalog opens the window.",
    add_completion=False,
)


def main() -> None:
    try:
        app()
    except LabCatalogError as err:
        typer.echo(f"Error: {err}", err=True)
        sys.exit(err.exit_code)
    except Exception:
        traceback.print_exc()
        sys.exit(EXIT_UNEXPECTED)


@app.callback(invoke_without_command=True)
def window(
    context: typer.Context,
    project: Annotated[
        Path | None,
        typer.Option("--project", "-p", help="Project folder to open when the window starts."),
    ] = None,
    browser: Annotated[
        bool,
        typer.Option(
            help="Show the pages in a web browser instead of a window, for example on a server "
            "reached through an SSH tunnel."
        ),
    ] = False,
    port: Annotated[
        int | None, typer.Option(help="Port to serve on; a free one when not given.")
    ] = None,
) -> None:
    if context.invoked_subcommand is not None:
        return
    # Imported here so check does not pay for loading the GUI stack.
    from labcatalog.gui import launch

    launch(project, browser, port)


@app.command()
def serve(
    projects: Annotated[
        Path,
        typer.Argument(help="Folder holding the projects to serve, each in a folder of its own."),
    ],
    port: Annotated[
        int | None, typer.Option(help="Port to serve on; a free one when not given.")
    ] = None,
    host: Annotated[
        str,
        typer.Option(
            help="Address to listen on: 127.0.0.1 for an SSH tunnel or a reverse proxy on this "
            "computer, 0.0.0.0 for everyone on the network who has the link."
        ),
    ] = "127.0.0.1",
) -> None:
    """Serve the projects in a folder to several people at once, in their browsers."""
    from labcatalog.gui import launch

    if not projects.is_dir():
        raise typer.BadParameter(f"{projects} is not a folder", param_hint="PROJECTS")
    launch(port=port, projects=projects, host=host)


@app.command()
def check(
    project: Annotated[
        Path, typer.Option("--project", "-p", help="Project folder containing labcatalog.yaml.")
    ] = Path("."),
) -> None:
    """Check the metadata and the data as the Problems page does; exit with 1 on any error."""
    report = run_check(project)
    show_report(report)
    raise typer.Exit(EXIT_ISSUES if report.has_errors() else EXIT_OK)


@app.command()
def run(
    project: Annotated[
        Path, typer.Option("--project", "-p", help="Project folder containing labcatalog.yaml.")
    ] = Path("."),
) -> None:
    """Run the outdated prepare steps, check the project and build its database, as a job."""
    from labcatalog.gui import preferences

    loaded, issues = load_validated(project)
    if loaded is None:
        show_report(reported(project, issues))
        raise typer.Exit(EXIT_ISSUES)
    tools = preferences.load()
    if datalad := tools.get(preferences.DATALAD):
        use_folder(datalad)
    names = [step.name for step in loaded.config.prepare]
    session = Session()
    try:
        runs = run_steps(
            loaded,
            names,
            session,
            outdated_only=True,
            echo=typer.echo,
            rscript=tools.get(preferences.RSCRIPT),
            datalad=datalad,
            python=preferences.step_python(),
        )
    except KeyboardInterrupt:
        # The step's command runs in a process group of its own, which Ctrl+C does not reach.
        stop(session)
        raise
    if not runs:
        typer.echo("Every step is up to date.")
    elif runs[-1].exit_code != 0:
        typer.echo(f"Step {runs[-1].name} {runs[-1].outcome}, so labcatalog stopped there.")
        raise typer.Exit(EXIT_ISSUES)
    result = run_catalog(project)
    if result.project is not None:
        write_database(result, result.project.root / defaults.DATABASE_FILE)
        typer.echo(f"Wrote {defaults.DATABASE_FILE}")
    show_report(result.report)
    raise typer.Exit(EXIT_ISSUES if result.report.has_errors() else EXIT_OK)


def show_report(report: CheckReport) -> None:
    for issue in report.issues:
        prefix = f"{issue.location}: " if issue.location else ""
        typer.echo(f"{prefix}{issue.level} [{issue.code}] {issue.message}")
    typer.echo(summarize_issues(report.issues))
    if report.accepted:
        typer.echo(
            f"{len(report.accepted)} warning(s) accepted in {defaults.ACCEPTED_FILENAME} "
            "are not shown."
        )
