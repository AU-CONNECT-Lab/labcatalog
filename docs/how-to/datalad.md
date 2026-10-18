# Using labcatalog with DataLad

labcatalog works without DataLad. When a project's files are in DataLad datasets, it also records which version of the data it read, lets a freeze tag that version so it can be opened again later, can run the prepare steps through `datalad run`, and can download file content a clone does not have yet.

## Install and connect

Install git-annex and DataLad yourself, for example with uv:

```bash
uv tool install git-annex
uv tool install datalad
```

On the Settings page, give the path to `datalad` (with uv on Windows it is usually `C:\Users\<you>\.local\bin\datalad.exe`) and press Save and check. labcatalog then puts that folder first on its own PATH, because git itself calls git-annex inside a dataset. The command line (`labcatalog prepare`, `labcatalog freeze`) uses the `datalad` on your PATH instead.

If the project's files are in a dataset but git-annex cannot be found, the check reports `git_annex_not_found`: the manifest then leaves out the dataset versions and History cannot show uncommitted changes.

## Recommended layout

Keep the metadata in git and the row-level data in the annex:

```bash
cd my_project
datalad create -c text2git --force .
echo "data/** annex.largefiles=anything" >> .gitattributes
echo "raw/** annex.largefiles=anything" >> .gitattributes
datalad save -m "Start the catalog"
```

`text2git` alone puts every text file in git, CSV files included. Pushing such a dataset to GitHub or any other git host publishes the data. The two `annex.largefiles` lines keep everything under `data/` and `raw/` in the annex, which only goes where you send it.

The data can also live in their own dataset, as a subdataset of the project (`datalad create -d . data`) or anywhere else on disk. labcatalog finds the nearest dataset of each file it reads, so any of these layouts works.

## Where to keep datasets

- Do not keep a dataset in a synced folder such as Box or OneDrive. Syncing tools and git-annex both rewrite files in the dataset and can corrupt it.
- Share through a sibling on a server or the university's storage, and give the sibling an absolute path or a URL. A relative path is copied as it is into every clone, where it no longer points at the store.
- On Windows, git-annex works in "adjusted mode": files are not locked, each file is stored twice (in the folder and in the annex), and operations are slower. Long paths can hit the 260-character limit, so keep the project folder near the top of a drive.
- On Linux and macOS, annexed files are locked. Edit one with `datalad unlock <file>` first, or let `datalad run` unlock the outputs of a step.

## Working from a clone

A clone has every file name but not the content of annexed files. labcatalog says which file is missing and how to get it, instead of reading the placeholder as data.

```bash
datalad clone <url of the dataset> my_project
cd my_project
datalad get -n data
```

`datalad get -n data` installs the `data` subdataset without downloading its files; skip it if the data are not a subdataset. Then open the project in labcatalog and press Get missing content, which downloads the metadata and every file the project reads (reference PDFs are downloaded one at a time when you open them). The **Prepare data** step of the Set up page also has a Get button next to each file that is not downloaded. On the command line, `labcatalog get` does the same as Get missing content.

In the window, **Open > Clone a project** does all of this at once: give where the project's dataset is (a URL, an SSH address or a folder, as `datalad clone` takes it) and the folder to put it in, and labcatalog clones it, downloads the files the project reads and opens it. `labcatalog datalad clone URL FOLDER` does the same on the command line.

## Saving, pushing and updating

The **Data versions** panel of the Datasets page keeps the datasets the project reads in step with their sibling, without a terminal. Its table lists each dataset (the one holding the project folder, and any subdataset or dataset elsewhere that holds data the project reads) with its unsaved changes, its sibling, the saved versions not pushed yet and the new versions on the sibling as of the last update. The header shows the same in a few words, such as **2 unsaved** or **1 to push**; click it to go to the panel.

- **Save** lists the changed files, asks what changed, and runs `datalad save` in each dataset with changes, deepest first, so a dataset above records the new versions of those inside it.
- **Push** runs `datalad push` to each dataset's sibling, deepest first. Unsaved changes stay on this computer until they are saved.
- **Update** runs `datalad update --how merge` from each sibling, the outermost dataset first, and then downloads the files the project reads, as **Get missing content** does.

A dataset is pushed to and updated from its only sibling, or `origin` when it has several; a dataset with several siblings and no `origin` is left for you to push from a terminal. The panel needs the path to datalad on the Settings page. On the command line, `labcatalog datalad status`, `save`, `update` and `push` do the same.

The table's **Here** column shows how much of each dataset's file content is on this computer. Below the table, pick a dataset (when there are several) and:

- **History** lists its last 50 saved versions, newest first, with when, who and what changed. A version that `datalad run` saved, such as a prepare step's, has **Rerun**, which runs its command again with `datalad rerun` and saves what it writes as a new version; like the prepare steps, it waits while someone else runs them.
- **Get everything** downloads all the dataset's file content.
- **Free space** removes the dataset's file content from this computer with `datalad drop`; the files stay listed and Get everything brings them back. DataLad leaves any file it cannot find a copy of elsewhere, so push first.

On the command line, `labcatalog datalad history`, `rerun` and `drop` do the same.

## Prepare steps through datalad run

Add this line to `labcatalog.yaml`:

```yaml
prepare_with: datalad
```

Each prepare step then runs as `datalad run --explicit` with the step's name as the commit message and its `inputs` and `outputs` as `-i` and `-o`. DataLad downloads missing inputs first, unlocks the outputs, and records the command, inputs and outputs in the dataset's history, so `datalad rerun` can repeat it. Braces in a command are passed to the script as written.

The project folder and every input and output must be inside a dataset (subdatasets included). Otherwise the step fails and its log shows DataLad's message.

## Freezes

A freeze (the Freeze button on the Datasets page, or `labcatalog freeze <name>`) writes a record of every data file labcatalog reads to `freezes/`: checksums, rows and participants. When the data are in DataLad, it also saves the files labcatalog uses and tags each dataset with the freeze's name.

The tag and the frozen data stay on your computer until you push them. `datalad push` sends neither tags nor the content of versions that are no longer the current one, so they have to be pushed right after freezing. When a dataset has one sibling, or several of which one is `origin`, the Freeze dialog offers **Then push the tag and the data to ...**, ticked by default, and `labcatalog freeze <name> --push` does the same. If the push fails, the freeze stays as it is. Push by hand with these two commands for each dataset, which is also what to do for a dataset whose sibling is not clear:

```bash
datalad push --to <sibling> --data anything
git push <sibling> <freeze name>
```

To see the data as they were at a freeze, open the Datasets page and press Open next to it in the Freezes table. labcatalog clones the datasets into a temporary folder, checks out the tag, downloads the files the project reads, and opens that copy. The window's title bar says whether every data file matches the freeze record; a mismatch usually means a data path in `labcatalog.yaml` is absolute or starts with `~`, so the copy read today's file. Edits in the copy do not change the project. Back to the project returns to it. On the command line, `labcatalog open-freeze <name> --to <folder>` makes the same copy in a folder you choose.
