# Scripts

The Scripts page holds every script of the project in one place: the scripts the [prepare steps](prepare.md) run, the analyses kept from the Custom tab of the [Analysis](analysis.md) page, and any other R or Python file in `scripts/` or `analyses/`. Beside a step in the **Add data** step of the Set up page, **Script** shows the script's code under the step, with a link to it here.

## The list

The bar above the list narrows it, as on the [Datasets](datasets.md) page. A script belongs to the datasets its steps write, and an analysis to the datasets it uses, so the **Search** box finds a script by its path, its steps' names, commands, inputs and outputs, or an analysis's request, and the filters choose by the **Study**, **Wave**, **Reporter** and **Modality** of those datasets, and by the lab's own dataset fields. Three more are the page's own: **Stage** (clean, process, extract, score, no stage, analyses, or not run), **Status** (of the steps that run it: up to date, outdated, missing output, missing input) and **Language**. The study chosen at the top of the window is where the filters start. A script that writes no dataset of the project stays in the list whatever study, wave, reporter or modality is chosen.

The scripts are listed on the left; click one to open it.

- The scripts the prepare steps run come first, grouped by the stage of their steps, then by the modality of the files those steps write, with the steps under each script. The stages follow the data: **Clean** turns a raw export into a dataset's file, **Process** runs a modality's pipeline on raw recordings, **Extract** gathers each person's pipeline output into one row per person, and **Score** computes an instrument's scores; a step whose `stage` is not set is under **No stage**. A script is found in the step's command or its inputs. One script can be run by several steps, such as one cleaning script for every wave, and is listed under each stage and modality its steps have. A step whose command names no script of the project, such as a command of its own program, is listed by its name; steps that write no dataset are under **Other**.
- **Analyses**: the scripts listed under `analyses` in `labcatalog.yaml`.
- **Not run**: R and Python files in `scripts/` and `analyses/` that nothing runs yet.

## A script

The top shows the script's code with its syntax coloured. Beside it, **What it gets and gives** lists each step that runs it with its command, what it reads and what it writes, and for each dataset it writes, its ID column, the columns its column map names and its missing codes. Change it there and press **Save**, or press **Open in your editor** to edit it in the program your computer opens it with. Saving a script puts the steps that run it out of date, since the script is one of their inputs. Choosing another script with unsaved changes asks first.

For a script that steps run, **Steps that run it** lists them as on the Add data step, each with its status, command, inputs and outputs, **Run** and **Log**, and two more buttons:

- **Edit** changes the step's name, stage, command, inputs and outputs. The command runs in the project folder; a file it reads is an input and a file it writes is an output, and every step writes at least one.
- **Remove** takes the step out of `labcatalog.yaml`. The script and the files stay.

**Add a step** adds a step that runs the script, starting from a command such as `Rscript scripts/tidy.R INPUT OUTPUT` for you to fill in. A step is checked before it is written, and refused if it would cause a problem, such as a step that writes its own input. Below the steps, the **Log** shows what the last step printed.

For an analysis, the panel shows what was asked for, its datasets and variables, and **Delete**, which deletes the script and its entry under `analyses`. It runs on the Custom tab.

When the project is in git, as every DataLad dataset is, **History** at the bottom lists the script's commits, newest first, with any change not yet saved as a version on top; open one to see what changed. The script is saved with the data in the same versions (see [Data versions](datasets.md#data-versions)), and a step run through DataLad records which version of the script made its files.

## New scripts

**New script** asks for the script's **Stage** and language, R or Python, then what it works on:

- **Clean**: the dataset it writes and the raw export it reads. The script is `scripts/clean_<dataset>`, with a `clean()` function that gets the export as a table and returns the clean table.
- **From a database**: the dataset it writes and the SQLite or DuckDB file it reads. The script is `scripts/query_<dataset>`, with a `QUERY` to write whose rows become the dataset's file; the lines below it open the database read only and run it. Its step `query_<dataset>` has the stage clean. See [Register Prepare Steps](../how-to/prepare-steps.md#from-a-database).
- **Extract**: the dataset it writes and the folder of pipeline output. The script starts with `FILES`, the path of each person's file within the folder, with `{id}` where the path holds the ID and `*` for any part of a name, such as `sub-{id}/ses-1/sub-*_ses-1_task-rest_eeg.tsv`. It is the rule [Add a data file](add-data.md) would suggest for the folder as it is now, for the dataset's wave, and the comment above it says how many people and files it counts; with nothing to go on, it is `{id}.*`, one file per person named after the ID. The script has a `features()` function that gets one person's file and returns their row; the lines below it find each person's file by `FILES` and write the table.
- **Process**: a name, the folder of raw recordings and the folder the pipeline writes. The script has a `process()` function that gets one recording and the folder to write to.
- **Score**: the instrument and the dataset, as on the instrument's page, which writes the scoring script with the columns of each score.
- **Other**: a name, for a script with only the lines that read its input file and write its output file.

A script for a stage begins with what it reads and writes: the command its step runs, the dataset's file, ID column, the columns its column map names and its missing codes. Only the function, or the query, is left to write; the lines after it apply it to the files. Its step, with its stage, is added to `labcatalog.yaml` with it, after the same check as **Add a step**.

**Draft a cleaning step**, at the bottom of the page, has a language model write a cleaning script for a dataset; see [Register Prepare Steps](../how-to/prepare-steps.md#draft-a-step-with-a-language-model).
