# Coded parent-child play: one row per child from each session's behaviour codes (behaviours by count and seconds).
# python scripts/extract_video.py <session folder> <clean file>
import csv
import sys
from pathlib import Path

MIN_MINUTES = 5

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "sessions.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_codes.csv", encoding="utf-8", newline="") as file:
        codes = {r["behavior"]: r for r in csv.DictReader(file)}
    minutes = float(person["minutes"])
    features = ["", "", "", ""]
    # Recordings cut short are too brief to give stable rates.
    if minutes >= MIN_MINUTES:
        features = [
            round(int(codes["child_positive"]["count"]) / minutes, 3),
            round(int(codes["child_negative"]["count"]) / minutes, 3),
            round(int(codes["parent_warmth"]["count"]) / minutes, 3),
            round(int(codes["joint_attention"]["seconds"]) / (minutes * 60), 4),
        ]
    rows.append([person["pid"], person["recorded"], *features, minutes])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "child_positive_rate", "child_negative_rate", "parent_warmth_rate", "joint_attention", "minutes"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} recordings too short")
