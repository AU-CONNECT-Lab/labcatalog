# Salivary cortisol: one row per child from the lab's assay report (every sample in duplicate, nmol/L).
# Rscript scripts/extract_saliva.R <assay report> <clean file>
MAX_CV <- 0.2
DETECTION_LIMIT <- 0.1

args <- commandArgs(trailingOnly = TRUE)
report <- args[1]
clean <- args[2]
samples <- read.csv(report, colClasses = "character")

# Below the detection limit counts as half the limit; duplicates that disagree are not used.
level <- function(sample) {
  if (nrow(sample) == 0) return(NA)
  reps <- c(sample$rep1, sample$rep2)
  reps <- ifelse(startsWith(reps, "<"), DETECTION_LIMIT / 2, suppressWarnings(as.numeric(reps)))
  if (sd(reps) / mean(reps) <= MAX_CV) mean(reps) else NA
}

hours <- function(time) {
  parts <- as.numeric(strsplit(time, ":")[[1]])
  parts[1] + parts[2] / 60
}

rows <- lapply(unique(samples$pid), function(pid) {
  found <- samples[samples$pid == pid, ]
  wake <- level(found[found$sample == "wake", ])
  wake30 <- level(found[found$sample == "wake30", ])
  bedtime <- level(found[found$sample == "bedtime", ])
  slope <- NA
  if (!is.na(wake) && !is.na(bedtime)) {
    span <- hours(found$time[found$sample == "bedtime"]) - hours(found$time[found$sample == "wake"])
    slope <- round((bedtime - wake) / span, 3)
  }
  data.frame(
    pid = pid, visit_date = found$date[1], cortisol_wake = round(wake, 2),
    cortisol_awakening = round(wake30 - wake, 2), cortisol_slope = slope,
    usable_samples = sum(!is.na(c(wake, wake30, bedtime)))
  )
})
out <- do.call(rbind, rows)

con <- file(clean, "wb")
write.csv(out, con, row.names = FALSE, quote = FALSE, na = "")
close(con)

cat(sprintf(
  "%s: %d children, %d missing a usable sample\n", report, nrow(out), sum(out$usable_samples < 3)
))
