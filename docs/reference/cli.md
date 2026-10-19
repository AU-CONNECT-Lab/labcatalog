# Command Line

labcatalog has three commands: one opens the window, one serves projects to several people in their browsers, and one checks a project for automation. Everything else is done in the window.

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

## check

```bash
labcatalog check [-p PROJECT]
```

Check the metadata and the data of the project folder (the current folder unless `--project`, `-p`, is given) exactly as the [Problems](../app/problems.md) page does, for automation such as a GitHub Actions workflow or a job on a cluster. It prints each problem as a line, `location: level [code] message`, then a summary, and says how many accepted warnings it left out. It exits with status 0 when there are no errors, 1 when there are, and 3 when the folder has no `labcatalog.yaml`. See [Fix Reported Problems](../how-to/fix-problems.md) and [Problem Codes](problem-codes.md).
