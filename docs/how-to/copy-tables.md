# Copy Tables into a Manuscript

Results on the Analysis, Methods and instrument pages are shown as three-line tables in APA style: a rule above, one below the header and one at the bottom, no vertical lines, statistical symbols in italics and a *Note.* under the table. Each one can be copied into a manuscript or saved with the data it came from.

## Choose the format

On the **Settings** page, under **Tables**, choose what the copy buttons copy:

- **Word or Google Docs**: rich text that pastes as a formatted table.
- **LaTeX**: a `booktabs` table. Add `\usepackage{booktabs}` to your preamble.

The number of decimal places is set for the whole project, under **This project** on the same page. *p* values always keep three and are written in APA style (".034", "< .001").

## Copy a table

Press **Copy table** (or **Copy as LaTeX**) under the table and paste it into your document. The table's number is a placeholder, "Table X", because you number tables in the manuscript.

Paragraphs, such as the Measures and Participants text on the Methods page, have a **Copy text** button that works the same way.

## Save to outputs

**Save to outputs** writes the table, and the figure if there is one, into a new folder in `outputs/`, named with the date, time and what was saved. Each table is written as `.csv`, `.docx` and `.tex`, and each figure as `.png` and `.svg`. **Open folder** opens it.

Every saved folder also contains `manifest.json`, which records the data files the numbers came from and their checksums. If someone asks later where a number in the paper came from, the manifest says which version of the data produced it.

## Reproduce a table

Every analysis has a **Code** section with the R and Python code that reproduces it from the data files. Copy it into a script to rerun the analysis outside labcatalog, change it, or give it to a reviewer.
