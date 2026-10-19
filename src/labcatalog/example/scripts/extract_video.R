# Coded parent-child play: one row per child from each session's behaviour codes (behaviours by count and seconds).
# Rscript scripts/extract_video.R <session folder> <clean file>
MIN_MINUTES <- 5

args <- commandArgs(trailingOnly = TRUE)
session <- args[1]
clean <- args[2]
people <- read.csv(file.path(session, "sessions.csv"), colClasses = c(pid = "character"))

rows <- lapply(seq_len(nrow(people)), function(i) {
  person <- people[i, ]
  codes <- read.csv(file.path(session, paste0(person$pid, "_codes.csv")), row.names = "behavior")
  minutes <- person$minutes
  rates <- c(NA, NA, NA, NA)
  # Recordings cut short are too brief to give stable rates.
  if (minutes >= MIN_MINUTES) {
    rates <- c(
      round(codes["child_positive", "count"] / minutes, 3),
      round(codes["child_negative", "count"] / minutes, 3),
      round(codes["parent_warmth", "count"] / minutes, 3),
      round(codes["joint_attention", "seconds"] / (minutes * 60), 4)
    )
  }
  data.frame(
    pid = person$pid, visit_date = person$recorded, child_positive_rate = rates[1],
    child_negative_rate = rates[2], parent_warmth_rate = rates[3], joint_attention = rates[4],
    minutes = minutes
  )
})
out <- do.call(rbind, rows)

con <- file(clean, "wb")
write.csv(out, con, row.names = FALSE, quote = FALSE, na = "")
close(con)

cat(sprintf(
  "%s: %d children, %d recordings too short\n", session, nrow(out),
  sum(is.na(out$child_positive_rate))
))
