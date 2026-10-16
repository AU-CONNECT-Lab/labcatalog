# Add an Instrument

There are four ways to add an instrument. Which one fits depends on what you start from:

| You have | Use |
|---|---|
| A new data file and its codebook (REDCap, Qualtrics, SPSS, or a document) | A codebook import, which also writes the column map |
| Only a PDF of the instrument | A draft from a language model |
| Nothing but the items | The Edit page, or write the file by hand |

## Import a codebook

A codebook import describes every column of one data file in three CSV files: `items.csv` (each column's instrument, item, wording, type and options), `instruments.csv` (each instrument's name, abbreviation and construct) and `scores.csv` (each score and its items). labcatalog checks them, then writes the instrument files and the dataset's column map. It works for a dataset that has no column map yet; add the dataset to `labcatalog.yaml` first (see [Add a Wave or Dataset](add-dataset.md)).

In the window:

1. Open the **Import** page and pick the dataset.
2. Create the three files. **Create the three files** lists the data file's columns and leaves the rest for you. If you have a codebook in a standard format, start from it instead: **Create from a REDCap data dictionary** (the CSV from REDCap's Data Dictionary page), **Create from a Qualtrics survey file** (the `.qsf` from Tools, Import/Export, Export Survey), or **Create from an SPSS file** (a `.sav` with variable and value labels). These fill in wording, options and item types.
3. Fill in what is still empty. **Open folder** opens `codebook/<dataset>/`; edit the files in Excel or any editor and save them as CSV UTF-8. **What goes in each column** explains every column.
4. Press **Check and import**. labcatalog lists every problem by file and line; fix them and press it again. When the files are right, it writes `instruments/<id>.yaml` for each new instrument and `maps/<dataset>.csv`.
5. Add the administrations. labcatalog does not change your study files, so the page shows the lines to add to `studies/<study>.yaml`. Then press **Refresh**.

Items whose wording is the same as an item already in the project are matched to it, so a later wave of a questionnaire you already have only adds its columns to the map.

The same steps on the command line:

```bash
labcatalog codebook create parent_w2 --redcap path/to/data_dictionary.csv
# fill in codebook/parent_w2/items.csv, instruments.csv and scores.csv
labcatalog codebook import parent_w2
```

### Let a language model fill in the files

If the codebook is a PDF or a document, a language model can fill in the three files for you. Under **Fill them in with an AI**, press **Copy AI prompt**, paste the prompt into the chat model of your choice together with the codebook, paste its answer into the box, and press **Replace the three files with this answer**. The prompt contains the format and the data file's column names, but no data. Check the files before you import them: the model can misread a codebook. On the command line, `labcatalog codebook prompt <dataset>` prints the same prompt.

## Draft an instrument from its PDF

With a language model set up on the Settings page (see [Set Up R and Language Models](r-and-models.md)), the **Edit** page can draft a whole instrument file, scores included, from the instrument's PDF:

1. On the **Edit** page, press **New instrument from a PDF**, give the instrument an ID, choose the PDF and press **Draft**. The PDF's text, including the item wording, is sent to the model's provider.
2. The draft is written to `drafts/<id>.yaml`, outside the catalog. Open it on the Edit page and check every item, option and score against the PDF.
3. Press **Move to instruments**. The instrument is now in the catalog.

You still map its columns and add its administration, as for any instrument. The references, the license and custom fields are always yours to fill in.

## Use the Edit page or write the file by hand

On the **Edit** page, **New instrument** creates `instruments/<id>.yaml` with the required keys. Switch to the table view to fill in items, response sets and scores as tables, or edit the YAML as text. [Instruments](../concepts/instruments.md) describes every key.

An editor works just as well. Start the file with this line, so that an editor with YAML support checks it and completes the keys as you type:

```yaml
# yaml-language-server: $schema=../schemas/instrument.schema.json
```

Then map the instrument's columns in each dataset's `maps/<dataset>.csv`, add an administration to the study file, and run `labcatalog validate`.
