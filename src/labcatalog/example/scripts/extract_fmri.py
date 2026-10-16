# Resting-state fMRI: one row per child from each child's network connectivity matrix (Fisher z).
# python scripts/extract_fmri.py <session folder> <clean file>
import csv
import sys
from pathlib import Path

MAX_FD = 0.5

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "motion.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_connectivity.csv", encoding="utf-8", newline="") as file:
        matrix = {r["network"]: r for r in csv.DictReader(file)}
    fd = float(person["mean_fd"])
    features = ["", "", "", ""]
    # Scans with too much head motion keep their motion value but no connectivity.
    if fd <= MAX_FD:
        features = [
            float(matrix["Default"]["Default"]),
            float(matrix["Control"]["Control"]),
            float(matrix["Default"]["Control"]),
            float(matrix["SalVentAttn"]["Default"]),
        ]
    rows.append([person["pid"], person["scanned"], *features, fd])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "dmn_within", "fpn_within", "dmn_fpn", "salience_dmn", "mean_fd"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} left out for motion")
