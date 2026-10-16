# Resting ECG: one row per child from each child's R-R intervals (ms, one per beat, with an artefact flag).
# python scripts/extract_ecg.py <session folder> <clean file>
import csv
import math
import statistics
import sys
from itertools import pairwise
from pathlib import Path

MIN_SECONDS = 180
MIN_CLEAN = 0.8

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "sessions.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_rr.csv", encoding="utf-8", newline="") as file:
        beats = list(csv.DictReader(file))
    seconds = sum(int(b["rr_ms"]) for b in beats) / 1000
    good = [int(b["rr_ms"]) for b in beats if b["artefact"] == "0"]
    share = len(good) / len(beats)
    features = ["", "", ""]
    # Short or noisy recordings give unstable variability, so only their length and quality are kept.
    if seconds >= MIN_SECONDS and share >= MIN_CLEAN:
        successive = [b - a for a, b in pairwise(good)]
        features = [
            round(60000 / statistics.mean(good), 1),
            round(math.sqrt(statistics.mean(d * d for d in successive)), 1),
            round(statistics.stdev(good), 1),
        ]
    rows.append([person["pid"], person["recorded"], *features, round(seconds), round(share, 3)])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "heart_rate", "rmssd", "sdnn", "seconds", "clean_beats"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} recordings too short or noisy")
