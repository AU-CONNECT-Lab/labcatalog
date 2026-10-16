# Edit

The Edit page edits the project's files: `labcatalog.yaml`, the instrument files, the drafts, the study files and the column maps. The files are listed on the left; click one to open it.

## Text mode

Every file opens as text. **Save** checks the file the same way loading the project does. If something is wrong, nothing is written, and each problem is listed under the editor with its line, which is also marked in the text. When the file is right, it is saved and the catalog reloads. **Reload from disk** throws away your changes.

## Table mode

Some parts of a file can also be edited as a table, chosen with the toggle above the editor:

| File | Tables |
|---|---|
| `labcatalog.yaml` | Datasets |
| Instrument files and drafts | Items, Scores, Response sets, and Custom fields when the project declares instrument fields |
| Study files | Administrations, Overrides |

Every cell can be edited; tick boxes and fixed choices show as such. Write lists with commas, for example `ems_1, ems_2`. **Add row** adds a row, **Delete ticked rows** deletes the rows you ticked, and dragging a row by its handle moves it. Saving changes only the cells you changed, so comments and the rest of the file stay as they were. A value set back to its default is removed from the file.

A file whose YAML cannot be read opens only as text; fix it there first.

## New instruments

- **New instrument** creates `instruments/<id>.yaml` with the required keys.
- **New instrument from a PDF** drafts a whole instrument with the language model set on the Settings page. The draft goes to `drafts/`, outside the catalog. Check it against the PDF, then press **Move to instruments**. See [Add an Instrument](../how-to/add-instrument.md).

## Unsaved changes

Opening another file or switching mode with unsaved changes asks whether to discard them. Pressing **Refresh**, or anything else that reloads the catalog, redraws the page without asking, so save first.
