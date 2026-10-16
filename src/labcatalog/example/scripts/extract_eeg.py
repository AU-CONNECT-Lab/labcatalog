# Resting-state EEG: one row per child from each child's band-power table (channels by bands, log10 µV²).
# python scripts/extract_eeg.py <session folder> <clean file>
import csv
import sys
from pathlib import Path

MIN_EPOCHS = 20

session, clean = Path(sys.argv[1]), sys.argv[2]
with open(session / "qc.csv", encoding="utf-8", newline="") as file:
    people = list(csv.DictReader(file))

rows = []
for person in people:
    with open(session / f"{person['pid']}_bandpower.csv", encoding="utf-8", newline="") as file:
        power = {r["channel"]: {b: float(r[b]) for b in ("theta", "alpha", "beta")} for r in csv.DictReader(file)}
    kept = int(person["epochs_kept"])
    features = ["", "", "", ""]
    # Too few clean epochs leaves the features blank; the epoch count still shows why.
    if kept >= MIN_EPOCHS:
        features = [
            round(power["F4"]["alpha"] - power["F3"]["alpha"], 4),
            round(sum(power[c]["theta"] for c in ("F3", "F4", "Fz")) / 3, 4),
            round(sum(power[c]["alpha"] for c in ("Pz", "O1", "O2")) / 3, 4),
            round(10 ** power["Fz"]["theta"] / 10 ** power["Fz"]["beta"], 3),
        ]
    rows.append([person["pid"], person["recorded"], *features, kept])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "frontal_alpha_asymmetry", "frontal_theta", "posterior_alpha", "theta_beta_ratio", "epochs_kept"])
    writer.writerows(rows)

print(f"{session}: {len(rows)} children, {sum(r[2] == '' for r in rows)} with too few epochs")
