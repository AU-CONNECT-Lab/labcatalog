import difflib
from dataclasses import dataclass, field

from labcatalog.llm import CallMetadata, LLMClient, ToolSchema

DRAFT_SYSTEM = """You write analysis scripts for researchers. You are given the columns of one \
data file, {data_file}, with what each holds, and the analysis the researcher wants. Write one \
{language} script that runs that analysis on the file.

The script runs in a folder that holds {data_file} and reads it from there by that name. It uses \
{libraries}. It prints its results as plain text, with labels a researcher can read. A figure is \
saved as a .png file and a table worth keeping as a .csv file, both in the same folder, under \
short names. It never writes over {data_file}.

Use the columns as they are: scores were computed by the project, items are already reversed \
where the scale says so, and a blank cell is a missing value. Handle missing values in the way \
usual for the analysis, and say which in a comment. Start each part of the script with a comment \
saying what it does.

In the notes, list each choice the request did not settle, such as which estimator or which \
covariates, and anything in the request the columns cannot give. Leave the notes empty when there \
is nothing to report. Leave the changes empty."""

FIX_SYSTEM = """You revise analysis scripts for researchers. You are given the columns of one \
data file, {data_file}, the analysis the researcher wants, a {language} script written for it, \
and what happened when it ran. Change the script so it runs and does the analysis, and change \
nothing else.

Return the whole revised script; it still reads {data_file} from its folder, uses {libraries}, \
prints its results and saves figures as .png and tables as .csv files. In the changes, say what \
you changed, one line each. In the notes, list what you could not fix from here, such as a \
package that is not installed. Leave the notes empty when there is nothing to report."""

SCHEMA = ToolSchema(
    name="analysis_script",
    description="An analysis script, what changed in it, and what it left open.",
    input_schema={
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "The whole script."},
            "changes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What changed in a revised script, one line each.",
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Choices left open, and what the columns cannot give.",
            },
        },
        "required": ["script", "changes", "notes"],
        "additionalProperties": False,
    },
)


@dataclass(frozen=True)
class Language:
    name: str
    suffix: str
    libraries: str


LANGUAGES = {
    "r": Language(
        "R",
        ".R",
        "base R and any CRAN package the analysis needs, loaded with library() at the top",
    ),
    "python": Language(
        "Python",
        ".py",
        "pandas, numpy, scipy, statsmodels, semopy and matplotlib, and nothing else",
    ),
}
# What happened when the script ran, cut to its end, where errors are.
SHOWN_OUTPUT = 4000


@dataclass
class AnalysisDraft:
    language: str
    script: str
    meta: CallMetadata
    # The script as it was, when the draft revises one.
    previous: str | None = None
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def diff(self) -> str:
        lines = difflib.unified_diff(
            (self.previous or "").splitlines(),
            self.script.splitlines(),
            "before",
            "after",
            lineterm="",
        )
        return "\n".join(lines)


def system_text(template: str, language: str, data_file: str) -> str:
    lang = LANGUAGES[language]
    return template.format(language=lang.name, libraries=lang.libraries, data_file=data_file)


def draft_request(columns: str, wanted: str) -> str:
    return f"{columns}\n\nThe analysis wanted:\n{wanted.strip()}"


def fix_request(columns: str, wanted: str, script: str, output: str) -> str:
    return "\n".join(
        [
            draft_request(columns, wanted),
            "",
            "The script:",
            "<script>",
            script,
            "</script>",
            "",
            "What it printed when it ran, ending with the error:",
            "<output>",
            output[-SHOWN_OUTPUT:],
            "</output>",
        ]
    )


def draft_analysis(
    columns: str, wanted: str, language: str, data_file: str, client: LLMClient
) -> AnalysisDraft:
    output, meta = client.complete_structured(
        system=system_text(DRAFT_SYSTEM, language, data_file),
        user_message=draft_request(columns, wanted),
        tool_schema=SCHEMA,
    )
    return AnalysisDraft(language, output["script"].strip() + "\n", meta, notes=output["notes"])


def fix_analysis(
    columns: str,
    wanted: str,
    language: str,
    data_file: str,
    script: str,
    ran: str,
    client: LLMClient,
) -> AnalysisDraft:
    output, meta = client.complete_structured(
        system=system_text(FIX_SYSTEM, language, data_file),
        user_message=fix_request(columns, wanted, script, ran),
        tool_schema=SCHEMA,
    )
    return AnalysisDraft(
        language,
        output["script"].strip() + "\n",
        meta,
        script,
        output["changes"],
        output["notes"],
    )
