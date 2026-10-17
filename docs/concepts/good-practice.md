# Keeping Data Safe

labcatalog reads your data and never changes them, but it cannot protect files from the people and tools around them. These are habits, not features of labcatalog; each one costs little to set up at the start of a project and a great deal to recover from later.

## Keep raw data read-only

Put the exports from your survey platform or acquisition software in `raw/` and never edit them by hand. Mark the files read-only. Make the cleaned files in `data/` with a script that reads `raw/`, so anyone can rebuild `data/` from the raw files and see every step in between. [Register Prepare Steps](../how-to/prepare-steps.md) lets labcatalog run those scripts and tell you when `data/` is older than its inputs.

## Put the project folder under version control

Keep `labcatalog.yaml`, `instruments/`, `studies/` and `maps/` in git. Every change to the metadata is then recorded with who made it and when, and a wrong edit can be undone. An instrument's page shows the history of its file when the project is in git. Data files can go in the same repository through DataLad; see [Using labcatalog with DataLad](../how-to/datalad.md).

## A synced folder is not a backup

Box, OneDrive and similar tools copy a deletion or an overwrite to every computer within seconds. Keep at least one copy that does not follow the sync, such as your institution's backed-up storage, and know how to use the version history your sync tool keeps. Check now and then that a file can actually be restored.

## Plan for sharing

Funders and journals increasingly ask for data to be shared with documentation. Since 2023, NIH has required a Data Management and Sharing Plan for the research it funds, and repositories such as the NIMH Data Archive and OSF expect a codebook with each dataset. An [export](../how-to/export-data.md) writes `variables.csv`, which lists every item and score with its wording, options, allowed range and missing codes, alongside the data. Open answers are never exported, but check the rest for anything that could identify a person before you share it.
