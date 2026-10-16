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

## Groups

Some people belong together: a parent and their child, siblings, pupils in a class. A group links them. Declare it under `ids`, with a name and how to read the group from each ID:

```yaml
ids:
  pattern: '^\d{4}[PC]$'
  group:
    name: family
    from_id: '^(\d{4})'
```

Here `1001P` and `1001C` are the parent and child of family `1001`. `from_id` is a regular expression whose first group is the group's ID. If the group cannot be read from the ID, leave out `from_id` and give each dataset a `group_column` instead.

Groups are used in three places:

- Correlations between datasets. A parent's stress and their child's mood are in different files with different IDs. `stats.correlate_by: family` pairs rows by family instead of by ID. The default is `id`; `none` turns off the correlations between scores on the instrument pages.

  When a file holds several people of one family, say two children, the family is taken person by person: each child is a row, rows of the same person in other files pair by ID, and a file with one row for the family (one parent) gives that row to each child. That parent then counts once for each child, so the rows are not independent; a multilevel model with people nested in families allows for that. When two files each hold several people of a family with no one in common (two children and two parents), their answers do not pair across those files. A parent's answers about a particular child go in a file of their own, one row per child with the child's ID, so they pair with that child.
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
