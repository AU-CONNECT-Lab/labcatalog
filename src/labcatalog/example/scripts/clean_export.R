# Turns one survey-platform export into the clean file labcatalog reads: Rscript scripts/clean_export.R <export> <clean>
PLATFORM <- c(
  "StartDate", "EndDate", "Status", "Progress", "Duration (in seconds)", "Finished",
  "RecordedDate", "ResponseId"
)

args <- commandArgs(trailingOnly = TRUE)
export <- args[1]
clean <- args[2]
rows <- read.csv(
  export,
  fileEncoding = "UTF-8-BOM", colClasses = "character", check.names = FALSE,
  na.strings = character()
)
columns <- setdiff(names(rows), c(PLATFORM, "pid"))

# Previews, unfinished attempts and the two label rows under the header all drop out here.
kept <- rows[rows$Finished == "True" & rows$Status != "Survey Preview", ]

# IDs stay as typed; labcatalog's check reports any that look wrong.
out <- data.frame(
  pid = kept$pid, visit_date = substr(kept$StartDate, 1, 10), kept[columns],
  check.names = FALSE
)
quoted <- function(x) ifelse(grepl("[\",\r\n]", x), paste0("\"", gsub("\"", "\"\"", x), "\""), x)
lines <- c(paste(names(out), collapse = ","), do.call(paste, c(lapply(out, quoted), sep = ",")))
con <- file(clean, "wb")
writeLines(lines, con, useBytes = TRUE)
close(con)

cat(sprintf("%s: kept %d of %d responses\n", export, nrow(kept), nrow(rows) - 2))
