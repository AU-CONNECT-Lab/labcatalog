# labcatalog runs: python scripts/extract_nback_w2.py raw/nback/ses-2 data/nback_w2.csv
# It writes data/nback_w2.csv, the file of the dataset nback_w2 (mock_study, wave 2, child, task):
#   one row per person, with the ID in pid.
# The columns its map (maps/nback_w2.csv) names: acc_1back, rt_1back, dprime_1back, acc_2back,
#   rt_2back, dprime_2back, no_response.
# Missing codes: -99 = refused, -98 = not applicable, -97 = don't know, "" = blank.
# FILES below is the rule that fits most of raw/nback/ses-2 now: 15 people, 15 files.
# Fill in features(), which gets one person's output and returns their row; the lines below it
#   apply it to the files.

import re
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

# Each person's file within the folder: {id} where its path holds the ID, * for any part of a name.
FILES = "{id}_nback_*_*.csv"
# A block counts when the child answered at least this many of its 40 trials.
MIN_TRIALS = 30


def features(path: Path) -> dict:
    trials = pd.read_csv(path)
    # PsychoPy's date is when the task started, such as 2025-03-01_10h15.32.123.
    row = {"visit_date": str(trials["date"].iloc[0])[:10]}
    # Practice trials leave the main loop's counter blank.
    trials = trials[trials["trials.thisN"].notna()]
    answered = trials["key_resp.keys"].isin(["j", "f"])
    z = NormalDist().inv_cdf
    for load in (1, 2):
        block = trials[trials["load"] == load]
        row.update({f"acc_{load}back": None, f"rt_{load}back": None, f"dprime_{load}back": None})
        if answered[block.index].sum() < MIN_TRIALS:
            continue
        correct = block["key_resp.corr"] == 1
        target = block["target"] == 1
        said_same = block["key_resp.keys"] == "j"
        # Adding half a trial to each count keeps rates of 0 or 1 finite (log-linear correction).
        hits = ((said_same & target).sum() + 0.5) / (target.sum() + 1)
        false_alarms = ((said_same & ~target).sum() + 0.5) / ((~target).sum() + 1)
        row[f"acc_{load}back"] = round(correct.mean(), 4)
        row[f"rt_{load}back"] = round(block.loc[correct, "key_resp.rt"].mean() * 1000, 1)
        row[f"dprime_{load}back"] = round(z(hits) - z(false_alarms), 3)
    row["no_response"] = int((~answered).sum())
    return row


def person_files(folder: Path) -> list[tuple[str, Path]]:
    pattern = re.escape(FILES).replace(r"\*", "[^/]*").replace(r"\{id\}", "(?P<id>[^/]+)")
    found = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if match := re.fullmatch(pattern, path.relative_to(folder).as_posix()):
            found.append((match["id"], path))
    return found


if __name__ == "__main__":
    folder, target = Path(sys.argv[1]), sys.argv[2]
    rows = [{"pid": person, **features(path)} for person, path in person_files(folder)]
    pd.DataFrame(rows).to_csv(target, index=False)
