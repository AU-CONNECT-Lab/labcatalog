# Working as a Team

Each person runs their own labcatalog, and everyone opens the same project folder. Nothing has to be installed on a server for that, and nobody needs an account in labcatalog: who did something is the name git knows for that person, or else their account name on the computer. This page describes three common ways labs share the folder.

## On a shared computer

When the lab signs in to one computer, for example through Remote Desktop, each person signs in with their own account and starts labcatalog as usual. Each account keeps its own settings (appearance, the path to R, the last project), and several people can have the same project open at once.

## On a server or cluster without a screen

On a computer reached only through SSH, such as a compute node of a cluster, start labcatalog in browser mode:

```bash
labcatalog gui --browser --port 8931 -p /path/to/project
```

It prints a link such as `http://127.0.0.1:8931/?token=...` and keeps running until you press Ctrl+C. labcatalog only answers on that computer itself, so connect your own computer to it with an SSH tunnel, in a second terminal on your own computer:

```bash
ssh -L 8931:127.0.0.1:8931 you@server
```

On a cluster where the program runs on a compute node, go through the login node to the node your job runs on:

```bash
ssh -J you@login.cluster -L 8931:127.0.0.1:8931 you@node-name
```

Then open the printed link in the browser on your own computer. The link holds a key made new each time labcatalog starts: a page opened without it is refused, because anyone signed in to the same computer can reach its local ports. The browser remembers the key until labcatalog stops.

In the browser, files are those of the server. Choosing a file shows the server's folders, so the files to work with have to be there first (copied with `scp`, a cluster's file browser, or a shared drive). Opening a file, such as a data file named in a problem, downloads a copy, and opening a folder copies its path on the server. Set the path to `Rscript` on the Settings page as on a desktop (on Linux often `/usr/bin/Rscript`, or the one a cluster's `module load R` puts on the PATH).

## In a synced folder

With the project in Box, OneDrive or a similar service, each person runs labcatalog on their own computer. The service copies each saved file to the others after a moment. When two people change the same file before the copies meet, the service keeps both, one of them as a conflict copy that labcatalog does not read; compare the two and keep one. A project that several people edit often is easier to keep in [DataLad](datalad.md), which records each change and brings changes together.

## When someone else changes the project

labcatalog reads the project when it opens it and when you press Refresh. When files change after that, because someone else saved or the sync service brought a new copy, a **Changed on disk** mark appears at the top; hold the pointer over it to see which files, and click it to read the project again. It does not read them again by itself, so nothing you have not saved is lost. Saving a file someone else changed after you opened it is refused, so the other change is not overwritten: open the file again and make your change there.

While someone runs the [prepare steps](prepare-steps.md), the project folder holds `prepare_running.json`, which names who and since when. Starting the steps meanwhile asks first, because two runs would write the same files; **Run anyway** is for a run that ended without cleaning up, for example when its window was closed. On the command line, delete the file once that run has ended.
