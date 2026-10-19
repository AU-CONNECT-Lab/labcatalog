# Working as a Team

Each person runs their own labcatalog, and everyone opens the same project folder. Nothing has to be installed on a server for that, and nobody needs an account in labcatalog: who did something is the name git knows for that person, or else their account name on the computer. This page describes three common ways labs share the folder, and a fourth where one labcatalog serves the whole lab.

## On a shared computer

When the lab signs in to one computer, for example through Remote Desktop, each person signs in with their own account and starts labcatalog as usual. Each account keeps its own settings (appearance, the path to R, the last project), and several people can have the same project open at once.

## On a server or cluster without a screen

On a computer reached only through SSH, such as a compute node of a cluster, start labcatalog in browser mode:

```bash
labcatalog --browser --port 8931 -p /path/to/project
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

### Run the steps as a job

When a pipeline on the cluster writes what the prepare steps read, such as each person's features or matrices, `labcatalog run` runs the outdated steps without the window, then checks the project and builds its database (see [Command Line](../reference/cli.md#run)). Press **Job command** on the Prepare steps of the Set up page to copy the command with the project's folder. A job script for Slurm, with the environment labcatalog is installed in:

```bash
#!/bin/bash
#SBATCH --job-name=labcatalog
#SBATCH --time=01:00:00
source ~/venvs/labcatalog/bin/activate
labcatalog run -p /path/to/project
```

To start it when the pipeline's job has ended well, give that job's number: `sbatch --dependency=afterok:123456 labcatalog_job.sh`. What the steps print goes to the job's output file, and the job fails when a step fails or the check finds errors. The steps use the Rscript, Python and DataLad set on the Settings page by the account that runs the job, so open labcatalog in browser mode once on the cluster to set them.

## One labcatalog for the whole lab

When the lab has a computer that stays on, such as the one everyone signs in to, one labcatalog can serve every project in a folder to everyone, in their own browsers; nobody else installs anything. The person who looks after that computer starts it:

```bash
labcatalog serve /path/to/projects --port 8931
```

It prints a link with a key, as browser mode does; give the link to the lab. Each person opening it is asked once for their name, which goes on what they change (accepted warnings, prepare steps they run, data versions they save), and then picks a project from the folder's projects (any folder inside it, up to two levels down, that holds a `labcatalog.yaml`). Choosing a file stays inside that folder. Each browser keeps its own appearance, chart colours, table format and last project; the paths to R, Mplus and DataLad are those of the person running labcatalog, set as on a desktop before starting it, and the Settings page only shows them. At most two analyses run in R at once (**Analyses in R at once** on the Settings page of a desktop labcatalog of that account), and a project read or a factor model fitted for one person is shared with the others until a file of the project changes.

labcatalog answers only on that computer itself unless started with `--host 0.0.0.0`; then everyone on the network who has the link can open it. Everyone with the link can open every project in the folder and run its prepare steps, which run commands on that computer as the person who started labcatalog, so give the link only to the lab. The link travels unencrypted, so on a network beyond the lab's own put a reverse proxy with HTTPS in front of it (most institutions' IT can set one up), or have people reach it through an SSH tunnel as above. The key is made new each time labcatalog starts, so the link changes after a restart.

## In a synced folder

With the project in Box, OneDrive or a similar service, each person runs labcatalog on their own computer. The service copies each saved file to the others after a moment. When two people change the same file before the copies meet, the service keeps both, one of them as a conflict copy that labcatalog does not read; compare the two and keep one. A project that several people edit often is easier to keep in [DataLad](datalad.md), which records each change and brings changes together.

## When someone else changes the project

labcatalog reads the project when it opens it and when you press Refresh. When files change after that, because someone else saved or the sync service brought a new copy, a **Changed on disk** mark appears at the top; hold the pointer over it to see which files, and click it to read the project again. It does not read them again by itself, so nothing you have not saved is lost. Saving a file someone else changed after you opened it is refused, so the other change is not overwritten: open the file again and make your change there.

While someone runs the [prepare steps](prepare-steps.md), the project folder holds `prepare_running.json`, which names who and since when. Starting the steps meanwhile asks first, because two runs would write the same files; **Run anyway** is for a run that ended without cleaning up, for example when its window was closed.
