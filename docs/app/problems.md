# Problems

The Problems page lists every problem `labcatalog check` finds: mismatches between the metadata and the data, and mistakes in the metadata itself. The count on the Problems tab is red when any problem is an error.

At the top are the number of errors and warnings, a toggle to show **All**, **Errors** or **Warnings**, and a **Search** box that filters the table.

## The table

The table shows each problem's level, the file and line it is in, the problem and its code. A project file (`labcatalog.yaml`, an instrument, draft or study file, or a column map) opens on the Edit page at that line. A data file opens in its own application.

## The Fix panel

**Fix** at the end of each row opens a panel about that one problem. It says what the problem means in plain words and who usually fixes it: you, whoever knows what a value should be, or the person who looks after the cleaning scripts.

For a problem in the data, the panel lists **The rows** it is about: the row of the data file (counting from the first line below the header), the ID and, where one column is at fault, its value. IDs with a space before or after them are shown in quotes so the space can be seen. Up to 50 rows are listed.

Where the fix is a change to the project files, the panel makes it for you:

| Problem | What the panel offers |
|---|---|
| `not_in_vocab` | A list of the allowed words with the closest one chosen, and **Use this word**. When the same slip is in several entries, **Use it in all N places** fixes them together. **Add '...' as a new word** adds it to `vocab` instead. |
| `unknown_reference` | Where one value holds the wrong ID (a study, an instrument or a dataset of an administration, an override's item, a response set), a list of the IDs it could be with the closest chosen, and **Use this ID**. |
| `reference_missing` | A list of the keys in `references.bib` with the closest chosen, and **Use this ID**. |
| `column_missing` | The data columns the map does not list yet, with the closest to the missing name chosen, and **Use this column**; or **Take the row out** when the data file does not hold that column. |
| `duplicate_id` | For a column map that lists one column twice, or maps one item to two columns: both lines, each with **Take this row out**. Other shared IDs only open the file, since renaming one may need changes elsewhere. |
| `missing_code_collision` | **... is an answer**, which takes the value out of the missing codes: in this dataset only (it gets its own `missing_codes`) or in every dataset. If the value really means no answer, the response set is wrong; open the instrument file. |
| `column_unmapped` | Each column the map does not list, to add to the map as not an item or as an item of an instrument given in that dataset. |
| `unmapped_item` | Each item without a column, with the data columns the map does not list yet (the likely one chosen), or **not asked in** the dataset, which records the item as dropped there. |
| `unexpected_value` | Each value, marked as a typo, a missing code (in this dataset only or in every dataset) or a new answer option. A new option changes the instrument, so it counts in every dataset. A typo stays in the data: labcatalog never changes data files. |
| `prepare_outdated`, `prepare_output_missing` | **Run ... again**, which runs that prepare step and shows its log if it stops with an error. |

A change is checked before it is saved, the same way loading the project checks the files. If the change would leave a new error, the panel says what labcatalog would report and saves nothing. Sometimes that error was already there and the first one hid it: a misspelled instrument in an administration stops labcatalog from checking that administration's datasets, so a misspelled dataset next to it only shows once the instrument is right. Then **Save anyway** saves the change, and the hidden problem appears in the table to fix next.

Every panel also has **Open** for the file the problem is in and **Copy a note**, which copies the problem, its file and its rows as text to send to whoever fixes it.

## Warnings that are fine

Some warnings need a look but no change: people who gave the same answer to every item may have answered that way. For a warning, the panel has a **Why it is fine** box and **It is fine**. The warning then leaves the table, and a section at the bottom of the page lists the warnings accepted so far, with who accepted each, when and why, and **Show again** to bring one back.

The record is kept in `accepted_warnings.yaml` in the project folder, so it travels with the project and its history. A warning comes back by itself when its message changes, for example when more people give the same answer. Errors cannot be accepted. [Problem Codes](../reference/problem-codes.md#accepted-warnings) describes the file.

Fix the files, then press **Refresh**. [Fix Reported Problems](../how-to/fix-problems.md) explains the common problems, and [Problem Codes](../reference/problem-codes.md) lists all of them.
