# Command Line

labcatalog has four commands: one opens the window, one serves projects to several people in their browsers, one runs a project's prepare steps as a job, and one checks a project for automation. Everything else is done in the window.

## Open the window

```bash
labcatalog [-p PROJECT] [--browser] [--port PORT]
```

With no command, labcatalog opens its window with the given project folder (`--project`, `-p`); without one, the project open when the window last closed, or the example the first time.

With `--browser` the pages open in a web browser instead of a window, for a computer with no screen of its own, such as a compute node reached through an SSH tunnel. labcatalog prints a link and serves only this computer (`127.0.0.1`); `--port` picks the port, otherwise a free one is used. In the browser, choosing a file shows the folders of the computer that runs labcatalog, and opening a file downloads a copy. See [Working as a Team](../how-to/work-as-a-team.md#on-a-server-or-cluster-without-a-screen).

The link holds a key made new each time labcatalog starts, and a page opened without it is refused, because anyone signed in to the same computer can reach its local ports. Open the printed link once; the browser then remembers the key until labcatalog stops. The window of the desktop app passes the key by itself.

## serve

```bash
labcatalog serve PROJECTS [--port PORT] [--host HOST]
```

Serve the projects in the folder `PROJECTS` to several people at once, in their browsers: each picks a project from the folder, gives their name once and keeps their own appearance and last project. labcatalog prints a link with a key, as `--browser` does. `--host` is `127.0.0.1` unless given, for an SSH tunnel or a reverse proxy on the same computer; `0.0.0.0` lets everyone on the network who has the link open it. See [Working as a Team](../how-to/work-as-a-team.md#one-labcatalog-for-the-whole-lab).

## run

```bash
labcatalog run [-p PROJECT]
```

Run the outdated prepare steps of the project folder (the current folder unless `--project`, `-p`, is given), then check the project and build its database, without the window: for a job on a cluster that follows the job of a pipeline whose output the steps read, or a job that runs every night. It runs the steps as **Run outdated** does on the [Prepare steps](../app/prepare.md#running), in order and each checked just before its turn, and prints what each one prints as it runs. Then it writes `database/labcatalog.duckdb` as **Build database** does (see [Query the Data in a Database](../how-to/database.md)) and prints the problems as `check` does. **Job command** on the Prepare steps copies this command with the project's folder.

A step that fails stops the rest, and then labcatalog neither checks the project nor builds the database. When the metadata have errors, labcatalog prints them and runs no step. Like the window, it does not start the steps while someone else is running those of the same project. Rscript, Python and DataLad are those set on the Settings page by the same account on the same computer; on a cluster, open labcatalog once in browser mode to set them (see [Working as a Team](../how-to/work-as-a-team.md#run-the-steps-as-a-job)). It exits with status 0 when every step succeeded and the check finds no errors, 1 when a step fails, the steps cannot start or the check finds errors, and 3 when the folder has no `labcatalog.yaml`.

## check

```bash
labcatalog check [-p PROJECT]
```

Check the metadata and the data of the project folder (the current folder unless `--project`, `-p`, is given) exactly as the [Problems](../app/problems.md) page does, for automation such as a GitHub Actions workflow or a job on a cluster. It prints each problem as a line, `location: level [code] message`, then a summary, and says how many accepted warnings it left out. It exits with status 0 when there are no errors, 1 when there are, and 3 when the folder has no `labcatalog.yaml`. See [Fix Reported Problems](../how-to/fix-problems.md) and [Problem Codes](problem-codes.md).
