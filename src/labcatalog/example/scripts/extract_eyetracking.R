# Eye tracking, faces task: one row per child from each child's fixation table (trials by areas of interest).
# Rscript scripts/extract_eyetracking.R <session folder> <clean file>
MAX_ERROR <- 1.5
MIN_LOOKING <- 1000

args <- commandArgs(trailingOnly = TRUE)
session <- args[1]
clean <- args[2]
people <- read.csv(file.path(session, "sessions.csv"), colClasses = "character")

rows <- lapply(seq_len(nrow(people)), function(i) {
  person <- people[i, ]
  fixations <- read.csv(file.path(session, paste0(person$pid, "_fixations.csv")))
  looking <- tapply(fixations$fixation_ms, fixations$trial, sum)
  face <- tapply(ifelse(fixations$aoi == "face", fixations$fixation_ms, 0), fixations$trial, sum)
  # A trial counts when the child looked at the screen for at least a second.
  valid <- looking >= MIN_LOOKING
  face_looking <- NA
  looking_ms <- NA
  if (as.numeric(person$calibration_error_deg) <= MAX_ERROR && any(valid)) {
    face_looking <- round(sum(face[valid]) / sum(looking[valid]), 4)
    looking_ms <- round(sum(looking[valid]) / sum(valid))
  }
  data.frame(
    pid = person$pid, visit_date = person$recorded, face_looking = face_looking,
    looking_ms = looking_ms, valid_trials = sum(valid),
    calibration_error = person$calibration_error_deg
  )
})
out <- do.call(rbind, rows)

con <- file(clean, "wb")
write.csv(out, con, row.names = FALSE, quote = FALSE, na = "")
close(con)

cat(sprintf(
  "%s: %d children, %d left out for calibration\n", session, nrow(out), sum(is.na(out$face_looking))
))
