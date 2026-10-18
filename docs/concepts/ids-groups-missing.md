# IDs, Groups and Missing Codes

labcatalog links datasets through participant IDs, can link people who belong together through a group, and needs to know which values mean "no answer".

## Participant IDs

Every dataset has an ID column, `id` unless `defaults.id_column` or the dataset's `id_column` says otherwise. The same person must have the same ID in every dataset where they appear, across waves and modalities. That is how labcatalog counts who took part in each wave, links a child's EEG to their questionnaires, and finds who left the study.

`ids.pattern` is a regular expression that every ID must match:

```yaml
ids:
  pattern: '^\d{4}[PC]$'
```

`labcatalog check` then reports IDs that do not match (`id_pattern`), IDs with leading or trailing spaces (`id_whitespace`), rows without an ID (`id_missing`) and IDs that appear twice in one file (`id_duplicate`).

### Correcting IDs

When a file writes IDs another way than the project, such as `sub-1001C`, `1001c` or `S12`, **Fix IDs** corrects them without touching the file. It opens from the **Fix** of an ID problem on the Problems page and from a dataset's page. Add rules, applied in order: remove a prefix or a suffix, find and replace (a regular expression), pad the number with zeros, remove spaces, or change the case. Type an ID in the **Corrected ID** column to set one by hand. The table shows, for every ID of the file, its corrected ID, whether that matches `ids.pattern` and whether the roster lists it, with the IDs still wrong and those that change first. Two IDs that would become the same are marked, and Save stays off until they differ. **Save** asks before it writes anything.

The corrections go to `id_map.csv` in the project folder, one line per ID:

```text
dataset,from,to
child_w1,sub-1001C,1001C
eeg_w1,S12,0012C
```

labcatalog applies them whenever it reads the dataset, to its ID column and its respondent column, so the checks, the catalog, the analyses and the exports all see the corrected IDs. Delete a line to undo it. `labcatalog check` reports a line that names a dataset the project does not have, gives an ID two corrections, or leaves the new ID empty (`id_map_invalid`). A cleaning script can still fix the file itself instead; then the line is no longer needed.

## Groups

Some people belong together: a parent and their child, siblings, pupils in a class. A group links them. Declare it under `ids` with a name of your choosing. When the ID holds the group, say how to read it:

```yaml
ids:
  pattern: '^\d{4}[PC]$'
  group:
    name: family
    from_id: '^(\d{4})'
```

Here `1001P` and `1001C` are the parent and child of family `1001`. `from_id` is a regular expression whose first group is the group's ID.

When every person has an ID of their own that says nothing of their group, list everyone once in a roster instead and give the group only its name:

```yaml
ids:
  group:
    name: family

roster:
  path: data/participants.csv
  id_column: pid
  group_column: family_id
```

The roster is a CSV file with one row per person: their ID, their group in a column you name, and any other columns you keep there, such as their role or birth year. Every dataset takes its people's groups from it, so a file that holds only a child's ID, such as an EEG file, still knows the child's family. Most labs already keep such a list, from recruitment or a demographics form; it can be made by one of your [prepare steps](../how-to/prepare-steps.md) like any other file. `from_id` and a roster's `group_column` are two ways of giving the same thing, so a project uses one of them.

The roster's other columns can be described like any data: name a `kind: demographics` instrument as `roster.instrument` and map the columns to its items in `maps/roster.csv`, listing the ID and group columns with no instrument, as in a dataset's map:

```yaml
roster:
  path: data/participants.csv
  id_column: pid
  group_column: family_id
  instrument: example_participants
```

The roster's values are then checked against the instrument's options and ranges, the instrument's page shows their distribution in the roster, and the Analysis page offers them for the people of every chosen file, for example the gender of the children in `child_w1` and of the parents in `parent_w1`, in Table 1, group comparisons and covariates. The instrument is not given in any dataset, so dataset pages do not list it.

With a roster, `labcatalog check` also reports IDs in the data that the roster does not list (`id_not_in_roster`), people the roster lists twice (`id_duplicate`) or without a group (`group_missing`), and, for information, people in the roster who are in no dataset yet (`roster_unused`).

A roster with a column of roles, one of `vocab.reporters` for each person, can name it as `role_column: role`. Each dataset's respondents are then checked against its `reporter`: a child's ID in a file of parents is reported (`reporter_mismatch`). The respondent is read from the dataset's `respondent_column` when it has one, so a parent's file about each child is checked against the parents. Roles that are not reporters are reported once (`role_unknown`), and the people with them are not checked.

Groups are used in three places:

- Correlations between datasets. A parent's stress and their child's mood are in different files with different IDs. `stats.correlate_by: family` pairs rows by family instead of by ID. The default is `id`; `none` turns off the correlations between scores on the instrument pages.

  When a file holds several people of one family, say two children, the family is taken person by person: each child is a row, rows of the same person in other files pair by ID, and a file with one row for the family (one parent) gives that row to each child. That parent then counts once for each child, so the rows are not independent; a multilevel model with people nested in families allows for that. When two files each hold several people of a family with no one in common (two children and two parents), their answers do not pair across those files. A parent's answers about a particular child go in a file of their own, one row per child with the child's ID, so they pair with that child; give the dataset a `respondent_column` with the parent's ID so that participant counts count the parent, not the child.
- Exports. `labcatalog export --by family` writes one wide row per family.
- Multilevel models, with people nested in groups.

## Missing codes

Many data files use codes such as `-99` for "refused". List them in `labcatalog.yaml`:

```yaml
missing_codes:
  - {code: -99, label: refused}
  - {code: -98, label: not applicable}
  - {code: "", label: blank}
```

Missing codes are counted and shown by label on the dataset and instrument pages, and never enter a score or a statistic. Blank cells always count as missing, whether or not a code for them is listed. A dataset with codes of its own sets `missing_codes` on its entry, which replaces the project's list for that file. A code that is also a response option of an item is reported as `missing_code_collision`.

## Exclusions

`exclusions` points to a CSV file with an `id` column that lists people or groups who must not be in the data, for example those who withdrew consent:

```yaml
exclusions: data/exclusions.csv
```

labcatalog does not remove anyone from your data. `labcatalog check` reports rows that belong to someone on the list (`excluded_present`), so you can remove them in your cleaning script.
