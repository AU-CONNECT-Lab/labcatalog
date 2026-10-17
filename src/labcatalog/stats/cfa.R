# Fits the factor models labcatalog writes to a folder and writes results.csv beside them.
args <- commandArgs(trailingOnly = TRUE)
folder <- args[1]
# wlsmv treats the items as ordered categories, ml as continuous.
ordinal <- args[2] == "wlsmv"

needed <- c("lavaan", "semTools")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) > 0) {
  cat(missing, sep = "\n")
  quit(status = 3)
}

measures <- if (ordinal) {
  c("chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.scaled", "tli.scaled", "rmsea.scaled",
    "rmsea.ci.lower.scaled", "rmsea.ci.upper.scaled", "srmr")
} else {
  c("chisq", "df", "pvalue", "cfi", "tli", "rmsea", "rmsea.ci.lower", "rmsea.ci.upper", "srmr")
}
rows <- list()
add <- function(model, what, factor = "", item = "", value = NA, message = "") {
  rows[[length(rows) + 1]] <<- data.frame(model = model, what = what, factor = factor,
                                          item = item, value = value, message = message)
}

fit_one <- function(model, syntax, data) {
  # Small samples often leave empty response cells; lavaan warns but the fit stands.
  fit <- withCallingHandlers(
    if (ordinal) {
      lavaan::cfa(syntax, data = data, ordered = names(data), estimator = "WLSMV", std.lv = TRUE)
    } else {
      lavaan::cfa(syntax, data = data, estimator = "ML", std.lv = TRUE)
    },
    warning = function(w) invokeRestart("muffleWarning")
  )
  if (!lavaan::lavInspect(fit, "converged")) {
    return(add(model, "problem", message = "the model did not converge"))
  }
  if (!suppressWarnings(lavaan::lavInspect(fit, "post.check"))) {
    return(add(model, "problem",
               message = "improper solution (a negative variance or a correlation above 1)"))
  }
  values <- lavaan::fitMeasures(fit, measures)
  for (name in names(values)) add(model, "fit", item = name, value = values[[name]])
  std <- lavaan::standardizedSolution(fit)
  std <- std[std$op == "=~", ]
  for (i in seq_len(nrow(std))) add(model, "loading", std$lhs[i], std$rhs[i], std$est.std[i])
  omega <- suppressWarnings(semTools::compRelSEM(fit))
  for (name in names(omega)) add(model, "omega", name, value = omega[[name]])
}

models <- read.csv(file.path(folder, "models.csv"), stringsAsFactors = FALSE)
for (i in seq_len(nrow(models))) {
  model <- models$model[i]
  data <- read.csv(file.path(folder, models$data[i]))
  tryCatch(
    fit_one(model, models$syntax[i], data),
    error = function(e) add(model, "problem", message = conditionMessage(e))
  )
}

columns <- data.frame(model = character(), what = character(), factor = character(),
                      item = character(), value = numeric(), message = character())
write.csv(do.call(rbind, c(list(columns), rows)), file.path(folder, "results.csv"),
          row.names = FALSE)
