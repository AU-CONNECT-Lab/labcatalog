# fNIRS social task: one row per child from each child's GLM table (channels by HbO and HbR betas per condition).
# python scripts/extract_fnirs.py <session folder> <clean file>
import csv
import sys
from pathlib import Path

PREFRONTAL = [f"ch{n}" for n in range(1, 9)]
MIN_GOOD = 4

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "qc.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_glm.csv", encoding="utf-8", newline="") as file:
        channels = list(csv.DictReader(file))
    # A channel the pipeline rejected for poor scalp coupling is left empty.
    good = [c for c in channels if c["hbo_social"] != ""]
    front = [c for c in good if c["channel"] in PREFRONTAL]
    features = ["", "", ""]
    if len(front) >= MIN_GOOD:
        social = sum(float(c["hbo_social"]) for c in front) / len(front)
        nonsocial = sum(float(c["hbo_nonsocial"]) for c in front) / len(front)
        features = [round(social, 4), round(nonsocial, 4), round(social - nonsocial, 4)]
    rows.append([person["pid"], person["recorded"], *features, len(good)])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "pfc_hbo_social", "pfc_hbo_nonsocial", "pfc_social_effect", "good_channels"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} with too few prefrontal channels")
