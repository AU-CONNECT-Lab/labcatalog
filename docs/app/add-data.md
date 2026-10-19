# Add Data

**Add data**, the second step of the Set up page, brings in the data files and links their columns to the instruments of the [Codebook](codebook.md) step. Its bar says how many prepare steps are not up to date and how many data files have no column map yet.

- **Add a data file** opens the same dialog as **Add a dataset** on the [Datasets](datasets.md) page: choose the file as it came from the survey platform or the lab's pipeline, its study, wave and reporter, then check the column of each item, which the dialog fills in where a column has an item's ID or a known name. It writes the dataset to `labcatalog.yaml`, its column map and the study's administrations.
- **Prepare steps**: the scripts that clean a file before it is read, such as an export with extra header rows or test runs, or that compute scores; see [Prepare Steps](prepare.md). A cleaning step is best added before the file's columns are linked, since the clean file is the one the catalog reads.
- **Files without a column map**: data files listed in `labcatalog.yaml` whose columns are not linked yet, described from a codebook of their own; see [Files Without a Column Map](import.md). Below it, **From a pipeline's table** brings in a pipeline's table of measures.
