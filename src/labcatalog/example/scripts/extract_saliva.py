# Salivary cortisol: one row per child from the lab's assay report (every sample in duplicate, nmol/L).
# python scripts/extract_saliva.py <assay report> <clean file>
import csv
import statistics
import sys

MAX_CV = 0.2
DETECTION_LIMIT = 0.1

report, clean = sys.argv[1], sys.argv[2]
with open(report, encoding="utf-8", newline="") as file:
    samples = list(csv.DictReader(file))


def level(sample):
    # Below the detection limit counts as half the limit; duplicates that disagree are not used.
    reps = [DETECTION_LIMIT / 2 if r.startswith("<") else float(r) for r in (sample["rep1"], sample["rep2"])]
    mean = statistics.mean(reps)
    return mean if statistics.stdev(reps) / mean <= MAX_CV else None


def hours(sample):
    h, m = sample["time"].split(":")
    return int(h) + int(m) / 60


people = {}
for s in samples:
    people.setdefault(s["pid"], {"date": s["date"]})[s["sample"]] = s

rows = []
for pid, found in people.items():
    levels = {name: level(found[name]) if name in found else None for name in ("wake", "wake30", "bedtime")}
    wake, wake30, bedtime = levels["wake"], levels["wake30"], levels["bedtime"]
    awakening = round(wake30 - wake, 2) if wake is not None and wake30 is not None else ""
    slope = ""
    if wake is not None and bedtime is not None:
        slope = round((bedtime - wake) / (hours(found["bedtime"]) - hours(found["wake"])), 3)
    usable = sum(v is not None for v in levels.values())
    rows.append([pid, found["date"], "" if wake is None else round(wake, 2), awakening, slope, usable])

with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", "cortisol_wake", "cortisol_awakening", "cortisol_slope", "usable_samples"])
    writer.writerows(rows)

print(f"{report}: {len(rows)} children, {sum(r[5] < 3 for r in rows)} missing a usable sample")
