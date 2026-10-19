# Add an Instrument

There are five ways to add an instrument. Which one fits depends on what you start from:

| You have | Use |
|---|---|
| A codebook (REDCap, Qualtrics, SPSS, or a document), with or without data yet | The **Codebook** step of the Set up page, before any data |
| A new data file and its codebook | A codebook import for that file, which also writes the column map |
| Only a PDF of the instrument | A draft from a language model |
| The items and a data file that has their columns | **Add an instrument** on the Instruments page |
| Nothing but the items | The editor in the Codebook step of the Set up page, or write the file by hand |

## Add it step by step

**Add an instrument** on the Instruments page asks for the instrument's name and answer options, takes the items pasted one per line, offers a total score, and finds the item columns in the datasets you choose. It writes the instrument file, the column map rows and the administrations in one go, after showing what each file gains. See [Instruments](../app/instruments.md#add-an-instrument). The same steps fill in an instrument that is missing a description, scores or a reference: open its page and press **Complete this instrument**.

## Before any data: the Codebook step

The **Codebook** step of the Set up page makes new instruments from a codebook without a data file: the same three CSV files in `codebook/_instruments/`, created empty or from a REDCap, Qualtrics or SPSS dictionary, filled in by hand or with a language model, then **Check and import** writes the instrument files. **Add data** then links a data file's columns to them. See [Codebook](../app/codebook.md).

## Import a codebook for a data file

A codebook import describes every column of one data file in three CSV files: `items.csv` (each column's instrument, item, wording, type and options), `instruments.csv` (each instrument's name, abbreviation, modality, whether it is a demographics form, and construct) and `scores.csv` (each score and its items). labcatalog checks them, then writes the instrument files and the dataset's column map. It works for a dataset that has no column map yet; add the dataset to `labcatalog.yaml` first (see [Add a Wave or Dataset](add-dataset.md)).

In the window:

1. Open the **Set up** page, go to its **Add data** step and, under **Files without a column map**, pick the dataset.
2. Create the three files. **Create the three files** lists the data file's columns and leaves the rest for you. If you have a codebook in a standard format, start from it instead: **Create from a REDCap data dictionary** (the CSV from REDCap's Data Dictionary page), **Create from a Qualtrics survey file** (the `.qsf` from Tools, Import/Export, Export Survey), or **Create from an SPSS file** (a `.sav` with variable and value labels). These fill in wording, options and item types.
3. Fill in what is still empty. **Open folder** opens `codebook/<dataset>/`; edit the files in Excel or any editor and save them as CSV UTF-8. **What goes in each column** explains every column.
4. Press **Check and import**. labcatalog lists every problem by file and line; fix them and press it again. When the files are right, it writes `instruments/<id>.yaml` for each new instrument and `maps/<dataset>.csv`.
5. Add the administrations. labcatalog does not change your study files, so the page shows the lines to add to `studies/<study>.yaml`. Then press **Refresh**.

Items whose wording is the same as an item already in the project are matched to it, so a later wave of a questionnaire you already have only adds its columns to the map.

### Let a language model fill in the files

If the codebook is a PDF or a document, a language model can fill in the three files for you. Under **Fill them in with an AI**, press **Copy AI prompt**, paste the prompt into the chat model of your choice together with the codebook, paste its answer into the box, and press **Replace the three files with this answer**. The prompt contains the format and the data file's column names, but no data. Check the files before you import them: the model can misread a codebook.

## Draft an instrument from its PDF

With a language model set up on the Settings page (see [Set Up R and Language Models](r-and-models.md)), the editor in the **Codebook** step of the Set up page can draft a whole instrument file, scores included, from the instrument's PDF:

1. In the editor in the **Codebook** step of the Set up page, press **New instrument from a PDF**, give the instrument an ID, choose the PDF and press **Draft**. When the PDF holds several instruments or versions, say which one to draft (for example "the short form"); otherwise the model drafts the one the PDF presents as the main one and names the others in its notes. The PDF's text, including the item wording, is sent to the model's provider.
2. The draft is written to `drafts/<id>.yaml`, outside the catalog. Open it in the editor and check every item, option and score against the PDF.
3. Press **Move to instruments**. The instrument is now in the catalog.

You still map its columns and add its administration, as for any instrument. The references, the license and custom fields are always yours to fill in.

## Use Edit Files or write the file by hand

In the editor in the **Codebook** step of the Set up page, **New instrument** creates `instruments/<id>.yaml` with the required keys. Switch to the table view to fill in items, response sets and scores as tables, or edit the YAML as text. [Instruments](../concepts/instruments.md) describes every key.

An editor works just as well. Start the file with this line, so that an editor with YAML support checks it and completes the keys as you type:

```yaml
# yaml-language-server: $schema=../schemas/instrument.schema.json
```

Then map the instrument's columns in each dataset's `maps/<dataset>.csv`, add an administration to the study file, and press **Refresh** to see any problem on the Problems page.
