# Tests invariance across waves for the models labcatalog writes to a folder; writes results.csv.
args <- commandArgs(trailingOnly = TRUE)
folder <- args[1]

needed <- c("lavaan", "semTools")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) > 0) {
  cat(missing, sep = "\n")
  quit(status = 3)
}

measures <- c("chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.scaled", "tli.scaled",
              "rmsea.scaled", "srmr")
steps <- list(configural = "", thresholds = "thresholds",
              metric = c("thresholds", "loadings"),
              scalar = c("thresholds", "loadings", "intercepts"))
rows <- list()
add <- function(model, step, what, item = "", value = NA, message = "") {
  rows[[length(rows) + 1]] <<- data.frame(model = model, step = step, what = what, item = item,
                                          value = value, message = message)
}

# The same item or factor across waves differs only in its _t<wave> ending.
by_stem <- function(names) split(names, sub("_t[0-9]+$", "", names))

fit_step <- function(syntax, data, equal) {
  # Small samples often leave empty response cells; lavaan warns but the fit stands.
  withCallingHandlers(
    semTools::measEq.syntax(
      syntax, data = data, ordered = names(data), estimator = "WLSMV", missing = "pairwise",
      parameterization = "theta", ID.fac = "std.lv", ID.cat = "Wu.Estabrook.2016",
      longFacNames = by_stem(lavaan::lavNames(syntax, "lv")), longIndNames = by_stem(names(data)),
      long.equal = equal, return.fit = TRUE
    ),
    warning = function(w) invokeRestart("muffleWarning")
  )
}

problem_of <- function(fit) {
  if (!lavaan::lavInspect(fit, "converged")) return("the model did not converge")
  if (!suppressWarnings(lavaan::lavInspect(fit, "post.check"))) {
    return("improper solution (a negative variance or a correlation above 1)")
  }
  ""
}

test_one <- function(model, syntax, data) {
  previous <- NULL
  for (step in names(steps)) {
    fit <- tryCatch(fit_step(syntax, data, steps[[step]]), error = function(e) conditionMessage(e))
    problem <- if (is.character(fit)) fit else problem_of(fit)
    # Every later step builds on the configural model, so nothing is testable without it.
    if (step == "configural" && problem != "") return(add(model, "", "problem", message = problem))
    if (problem != "") {
      add(model, step, "problem", message = problem)
      previous <- NULL
      next
    }
    values <- lavaan::fitMeasures(fit, measures)
    for (name in names(values)) add(model, step, "fit", name, values[[name]])
    if (!is.null(previous)) {
      test <- tryCatch(suppressWarnings(lavaan::lavTestLRT(previous, fit)),
                       error = function(e) NULL)
      if (!is.null(test)) {
        add(model, step, "compare", "chisq_diff", test[2, "Chisq diff"])
        add(model, step, "compare", "df_diff", test[2, "Df diff"])
        add(model, step, "compare", "p_diff", test[2, "Pr(>Chisq)"])
      }
    }
    previous <- fit
  }
}

models <- read.csv(file.path(folder, "models.csv"), stringsAsFactors = FALSE)
for (i in seq_len(nrow(models))) {
  model <- models$model[i]
  data <- read.csv(file.path(folder, models$data[i]))
  tryCatch(
    test_one(model, models$syntax[i], data),
    error = function(e) add(model, "", "problem", message = conditionMessage(e))
  )
}

columns <- data.frame(model = character(), step = character(), what = character(),
                      item = character(), value = numeric(), message = character())
write.csv(do.call(rbind, c(list(columns), rows)), file.path(folder, "results.csv"),
          row.names = FALSE)
