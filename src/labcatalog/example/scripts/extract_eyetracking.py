# Eye tracking, faces task: one row per child from each child's fixation table (trials by areas of interest).
# python scripts/extract_eyetracking.py <session folder> <clean file>
import csv
import sys
from pathlib import Path

MAX_ERROR = 1.5
MIN_LOOKING = 1000

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "sessions.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_fixations.csv", encoding="utf-8", newline="") as file:
        fixations = list(csv.DictReader(file))
    trials = {}
    for f in fixations:
        trials.setdefault(f["trial"], {})[f["aoi"]] = int(f["fixation_ms"])
    # A trial counts when the child looked at the screen for at least a second.
    valid = [t for t in trials.values() if sum(t.values()) >= MIN_LOOKING]
    features = ["", ""]
    if float(person["calibration_error_deg"]) <= MAX_ERROR and valid:
        looking = sum(sum(t.values()) for t in valid)
        features = [round(sum(t["face"] for t in valid) / looking, 4), round(looking / len(valid))]
    rows.append([person["pid"], person["recorded"], *features, len(valid), person["calibration_error_deg"]])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "face_looking", "looking_ms", "valid_trials", "calibration_error"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} left out for calibration")
