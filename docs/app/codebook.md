# Codebook

**Codebook**, the first step of the Set up page, describes the instruments before there is any data: their items, answer options and scores. The next step, [Add data](add-data.md), then links a data file's columns to their items.

## Instruments

The instruments already in the project, with their numbers of items and scores. Drafts in `drafts/` waiting to be checked are named under the table, and the step bar says how many there are. **New instrument** and **Draft from a PDF** open the dialogs of the [Edit files](edit.md) step: an empty instrument file to fill in, or a draft a language model writes from the instrument's PDF (see [Add an Instrument](../how-to/add-instrument.md)).

## From a codebook

New instruments from a data dictionary or any codebook, in three CSV files in `codebook/_instruments/`: `items.csv` (each item's instrument, ID, wording, type and options, and the variable name the data will use for it when the codebook gives one), `instruments.csv` (each instrument's name, abbreviation and construct) and `scores.csv` (each score and its items).

1. **Codebook files**: **Create empty files**, or start from a codebook in a standard format: **Create from a REDCap data dictionary**, **Create from a Qualtrics survey file** or **Create from an SPSS file**, which fill in each item's wording, options and type, with each REDCap form or Qualtrics block as an instrument. Items worded like an item already in the project, and the ID field, are left out. The dictionary itself is kept in `codebook/_instruments/source/`; **Keep the codebook** beside the heading keeps any other file there too, such as a PDF, and opens the ones kept. **What goes in each column** explains every column.
2. **Fill them in with an AI** (optional): **Copy AI prompt** copies a prompt with the format, what the files hold so far and the instruments already in the project. Paste it into a chat model with your codebook, paste the answer into **The AI's answer**, and press **Replace the three files with this answer**.
3. **Import**: **Check and import** checks the three files and lists every problem by file and line. When there are none, it writes one file in `instruments/` for each new instrument, then moves the three files to `codebook/_instruments_<date>/`, so the next codebook starts from empty files.
