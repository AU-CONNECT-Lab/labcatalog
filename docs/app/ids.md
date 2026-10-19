# Check IDs

**Check IDs**, the third step of the Set up page, lists each data file the catalog reads with its study, its number of rows and of different IDs, and what is wrong with its IDs: rows with no ID, IDs with spaces, IDs that do not match the study's ID pattern (`id_pattern`, or `ids.pattern` for the whole project), IDs that appear more than once, IDs not in the study's roster, and IDs that give no group. Beside each problem, its IDs are listed as the file writes them (in quotes when they hold spaces), or the lines of the rows with no ID. A file with none of these says **All right**; one with IDs already corrected says how many.

**Fix IDs** beside each file opens the dialog that corrects them by rules (remove a prefix or a suffix, find and replace, pad the number with zeros, remove spaces, change the case) and by hand, with a preview that marks each new ID against the pattern and the roster and shows which are still not right. The corrections are kept in `id_map.csv` and applied as the data are read; the data files stay as they are. See [IDs, Groups and Missing Values](../concepts/ids-groups-missing.md).

Problems with a roster's own IDs are not changed here: correct them in the roster file. **See them in Problems** lists them.
