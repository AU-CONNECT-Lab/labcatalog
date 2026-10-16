from datetime import date
from pathlib import Path

from labcatalog import defaults
from labcatalog.config import dataset_by_name, missing_codes_for
from labcatalog.data.resolve import Catalog, as_text_dict
from labcatalog.datalad.annex import is_placeholder
from labcatalog.exceptions import LLMError
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.metadata.bibliography import citation
from labcatalog.project import Project, reference_pdf
from labcatalog.schema import Instrument, Item, Reference

SYSTEM = """You write scoring scripts for questionnaires used in research. You are given an \
instrument's reference (its paper or manual, converted from PDF), the instrument's items, and \
how one dataset stores them. Write an R script and a Python script that compute every score the \
reference defines, the way the reference says to compute it.

The scripts run on a data frame `d` that already holds the dataset (R: read with read.csv(); \
Python: read with pandas.read_csv()). Add one new column per score to `d`, named \
<score>_<dataset> in lower case with underscores, for example total_child_w1. Do not read or \
write files, and use only base R, pandas and numpy.

Treat the dataset's missing codes, and any value that is not one of an item's options, as \
missing. Reverse-score items as the reference says. Apply the reference's rule for missing \
answers, such as a minimum number of answered items or prorating; if it gives none, require \
every item and say so in the notes. Start each score's block with a comment naming the score.

The two scripts must give the same numbers. In the notes, list each decision the reference did \
not settle, and anything in the reference that disagrees with the items given here, such as a \
different number of items or different reverse-scored items. Leave the notes empty when there \
is nothing to report."""

SCHEMA = ToolSchema(
    name="scoring_scripts",
    description="Scripts that score the instrument in one dataset, and what the reference left open.",
    input_schema={
        "type": "object",
        "properties": {
            "r": {"type": "string", "description": "The R script."},
            "python": {"type": "string", "description": "The Python script."},
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Decisions the reference did not settle, and disagreements.",
            },
        },
        "required": ["r", "python", "notes"],
        "additionalProperties": False,
    },
)
READERS = {"r": "read.csv()", "python": "pandas.read_csv()"}
SUFFIXES = {"r": ".R", "python": ".py"}


def script_paths(project: Project, instrument_id: str, dataset: str) -> dict[str, Path]:
    folder = project.root / defaults.SCORING_DIR
    return {k: folder / f"{instrument_id}_{dataset}{suffix}" for k, suffix in SUFFIXES.items()}


def reference_pdfs(project: Project, instrument: Instrument) -> list[tuple[Reference, Path]]:
    found = [(r, reference_pdf(project, r.pdf)) for r in instrument.references if r.pdf]
    return [(r, path) for r, path in found if path.is_file() and not is_placeholder(path)]


def pdf_text(path: Path) -> str:
    # Markdown keeps the tables that scoring keys are often printed in.
    try:
        import pymupdf4llm
    except ImportError as e:
        raise LLMError("The pymupdf4llm package is missing: pip install labcatalog[ai]") from e
    return pymupdf4llm.to_markdown(str(path), show_progress=False)


def scoring_request(project: Project, catalog: Catalog, instrument_id: str, dataset: str) -> str:
    instrument = project.instruments[instrument_id]
    columns = {
        v.item_id: v.column
        for v in catalog.variables_for(dataset)
        if v.instrument_id == instrument_id
    }
    name = instrument.name + (f" ({instrument.abbreviation})" if instrument.abbreviation else "")
    lines = [
        f"Instrument: {name}",
        f"Dataset: {dataset}",
        "",
        "Items (id | column in this dataset | text | answer | reverse-scored in the catalog):",
    ]
    for item in instrument.items:
        if item.id in columns:
            reverse = "yes" if item.reverse else "no"
            text = " / ".join(as_text_dict(item.text).values())
            lines.append(
                f"{item.id} | {columns[item.id]} | {text} | {answer(instrument, item)} | {reverse}"
            )
    config = project.config
    codes = missing_codes_for(config, dataset_by_name(config, dataset))
    listed = ", ".join(f"{c.code} = {c.label}" for c in codes) or "none"
    lines += ["", f"Missing codes in this dataset: {listed}"]
    for reference, path in reference_pdfs(project, instrument):
        cited = citation(project.bibliography, reference.key)
        lines += ["", f"Reference: {cited}", "<reference>", pdf_text(path)]
        lines.append("</reference>")
    return "\n".join(lines)


def answer(instrument: Instrument, item: Item) -> str:
    if item.type == "choice":
        name = item.response_set or instrument.default_response_set
        options = next(s for s in instrument.response_sets if s.id == name).options
        return "options " + ", ".join(f"{o.value} = {o.label}" for o in options)
    if item.type == "number":
        bounds = [
            f"{word} {v:g}" for word, v in (("min", item.min), ("max", item.max)) if v is not None
        ]
        return " ".join(["number", *bounds])
    return item.type


def write_scoring_scripts(
    project: Project, catalog: Catalog, instrument_id: str, dataset: str, client: LLMClient
) -> CallMetadata:
    request = scoring_request(project, catalog, instrument_id, dataset)
    output, meta = client.complete_structured(
        system=SYSTEM, user_message=request, tool_schema=SCHEMA
    )
    instrument = project.instruments[instrument_id]
    sources = ", ".join(path.name for _, path in reference_pdfs(project, instrument))
    for language, path in script_paths(project, instrument_id, dataset).items():
        header = [
            f"# {instrument.name}, dataset {dataset}: written by {meta.provider} {meta.model} "
            f"on {date.today().isoformat()} from {sources}.",
            "# Check it against the reference before using it.",
            f"# d is the dataset read with {READERS[language]}",
            *(["# Notes from the model:"] if output["notes"] else []),
            *[f"# - {line}" for line in output["notes"]],
        ]
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            "\n".join(header) + "\n\n" + output[language].strip() + "\n", encoding="utf-8"
        )
    return meta
