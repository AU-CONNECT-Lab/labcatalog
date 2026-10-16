# Tests invariance for the models labcatalog writes to a folder; writes results.csv.
# Arguments: the folder, the estimator, and "steps" to fit every step or "score" for score tests.
args <- commandArgs(trailingOnly = TRUE)
folder <- args[1]
# wlsmv treats the items as ordered categories, ml as continuous.
ordinal <- args[2] == "wlsmv"
action <- args[3]

needed <- c("lavaan", "semTools")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) > 0) {
  cat(missing, sep = "\n")
  quit(status = 3)
}

if (ordinal) {
  measures <- c("chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.scaled", "tli.scaled",
                "rmsea.scaled", "srmr")
  steps <- list(configural = "", thresholds = "thresholds",
                metric = c("thresholds", "loadings"),
                scalar = c("thresholds", "loadings", "intercepts"))
  added <- list(thresholds = "|", metric = "=~", scalar = "~1")
} else {
  measures <- c("chisq", "df", "pvalue", "cfi", "tli", "rmsea", "srmr")
  steps <- list(configural = "", metric = "loadings", scalar = c("loadings", "intercepts"))
  added <- list(metric = "=~", scalar = "~1")
}
rows <- list()
add <- function(model, step, what, item = "", value = NA, message = "") {
  rows[[length(rows) + 1]] <<- data.frame(model = model, step = step, what = what, item = item,
                                          value = value, message = message)
}

# The same item or factor across occasions differs only in its _t<occasion> ending.
stem <- function(names) sub("_t[0-9]+$", "", names)
by_stem <- function(names) split(names, stem(names))

fit_step <- function(syntax, data, equal, partial, group) {
  free <- if (partial == "") "" else strsplit(partial, "; ", fixed = TRUE)[[1]]
  items <- setdiff(names(data), group)
  options <- list(configural.model = syntax, data = data, ID.fac = "std.lv", return.fit = TRUE)
  options <- c(options, if (ordinal) {
    list(ordered = items, estimator = "WLSMV", missing = "pairwise", parameterization = "theta",
         ID.cat = "Wu.Estabrook.2016")
  } else {
    # Full-information ML keeps the people missing an occasion.
    list(estimator = "ML", missing = "ml")
  })
  options <- c(options, if (group == "") {
    list(longFacNames = by_stem(lavaan::lavNames(syntax, "lv")), longIndNames = by_stem(items),
         long.equal = equal, long.partial = free)
  } else {
    list(group = group, group.equal = equal, group.partial = free)
  })
  # Small samples often leave empty response cells; lavaan warns but the fit stands.
  withCallingHandlers(do.call(semTools::measEq.syntax, options),
                      warning = function(w) invokeRestart("muffleWarning"))
}

problem_of <- function(fit) {
  if (!lavaan::lavInspect(fit, "converged")) return("the model did not converge")
  if (!suppressWarnings(lavaan::lavInspect(fit, "post.check"))) {
    return("improper solution (a negative variance or a correlation above 1)")
  }
  ""
}

test_one <- function(model, entry, data) {
  previous <- NULL
  for (step in names(steps)) {
    fit <- tryCatch(fit_step(entry$syntax, data, steps[[step]], entry$partial, entry$group),
                    error = function(e) conditionMessage(e))
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

# One score test per item: releasing all the constraints the step adds for that item.
score_one <- function(model, entry, data) {
  step <- entry$step
  fit <- fit_step(entry$syntax, data, steps[[step]], entry$partial, entry$group)
  table <- lavaan::parTable(fit)
  constraints <- table[table$op == "==", ]
  target <- table[match(constraints$lhs, table$plabel), ]
  observed <- lavaan::lavNames(fit, "ov")
  wanted <- target$op == added[[step]] & (target$op != "~1" | target$lhs %in% observed)
  items <- stem(ifelse(target$op == "=~", target$rhs, target$lhs))
  for (item in unique(items[wanted])) {
    release <- which(wanted & items == item)
    found <- lavaan::lavTestScore(fit, release = release, univariate = FALSE, epc = FALSE)$test
    # The mean-scaled test is the robust one under WLSMV; ML has only the standard test.
    row <- found[found$test == (if ("score.scaled" %in% found$test) "score.scaled" else "score"), ]
    add(model, step, "score", item, row$X2, "chisq")
    add(model, step, "score", item, row$df, "df")
    add(model, step, "score", item, row$p.value, "p")
  }
}

models <- read.csv(file.path(folder, "models.csv"), stringsAsFactors = FALSE,
                   colClasses = "character")
for (i in seq_len(nrow(models))) {
  entry <- models[i, ]
  data <- read.csv(file.path(folder, entry$data))
  run <- if (action == "score") score_one else test_one
  tryCatch(
    run(entry$model, entry, data),
    error = function(e) add(entry$model, "", "problem", message = conditionMessage(e))
  )
}

columns <- data.frame(model = character(), step = character(), what = character(),
                      item = character(), value = numeric(), message = character())
write.csv(do.call(rbind, c(list(columns), rows)), file.path(folder, "results.csv"),
          row.names = FALSE)
