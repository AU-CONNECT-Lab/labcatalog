# Turns one survey-platform export into the clean file labcatalog reads: python scripts/clean_export.py <export> <clean>
import csv
import sys

PLATFORM = [
    "StartDate",
    "EndDate",
    "Status",
    "Progress",
    "Duration (in seconds)",
    "Finished",
    "RecordedDate",
    "ResponseId",
]

export, clean = sys.argv[1], sys.argv[2]
with open(export, encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    columns = [c for c in reader.fieldnames if c not in PLATFORM and c != "pid"]
    rows = list(reader)

# Previews, unfinished attempts and the two label rows under the header all drop out here.
kept = [r for r in rows if r["Finished"] == "True" and r["Status"] != "Survey Preview"]

# IDs stay as typed; labcatalog's check reports any that look wrong.
with open(clean, "w", encoding="utf-8", newline="") as file:
    writer = csv.writer(file, lineterminator="\n")
    writer.writerow(["pid", "visit_date", *columns])
    for r in kept:
        writer.writerow([r["pid"], r["StartDate"][:10], *(r[c] for c in columns)])

print(f"{export}: kept {len(kept)} of {len(rows) - 2} responses")
