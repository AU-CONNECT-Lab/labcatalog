SCHEMA_VERSION = 1

CONFIG_FILENAME = "labcatalog.yaml"
ACCEPTED_FILENAME = "accepted_warnings.yaml"
# Corrections of IDs as the data files write them, applied whenever a dataset is read.
ID_MAP_FILENAME = "id_map.csv"
# Who is running the prepare steps, there only while they run.
PREPARE_LOCK_FILENAME = "prepare_running.json"
YAML_SUFFIXES = (".yaml", ".yml")
INSTRUMENTS_DIR = "instruments"
STUDIES_DIR = "studies"
MAPS_DIR = "maps"
SCHEMAS_DIR = "schemas"
CODEBOOK_DIR = "codebook"
SCORING_DIR = "scoring"
DRAFTS_DIR = "drafts"
DATA_DIR = "data"
SCRIPTS_DIR = "scripts"
ANALYSES_DIR = "analyses"
# A study's roster read like a dataset is roster_<study>, with its column map in maps/.
ROSTER = "roster"
BIB_FILENAME = "references.bib"
OUTPUTS_DIR = "outputs"
FREEZES_DIR = "freezes"
DATABASE_FILE = "database/labcatalog.duckdb"
MANIFEST_FILENAME = "manifest.json"
SCORE_PREFIX = "score:"

ID_COLUMN = "id"
DATE_FORMAT = "%Y-%m-%d"
BLANK_LABEL = "blank"
MIN_CORRELATION_N = 3
CORRELATE_BY = "id"
DECIMALS = 2
IMPUTATIONS = 20
SEED = 1
LLM_PROVIDER = "anthropic"
SAME_ANSWER_MIN_ITEMS = 5
DEFAULT_MODALITIES = ("questionnaire",)
BUILTIN_FACETS = ("study", "wave", "coverage", "reporter", "target", "modality", "status")
# About the catalog rather than the scores, so the score network cannot color by them.
CATALOG_FACETS = ("coverage", "status")
DEFAULT_FACETS = ("study", "wave", "coverage", "reporter", "target", "modality")
# Last in the default filters, after the custom fields.
DEFAULT_LAST_FACETS = ("status",)
FACET_FIELD_TYPES = ("choice", "tags")

EXAMPLE_VALUES = 3
HISTOGRAM_BINS = 20
IDENTIFIER_NAME_PATTERNS = (
    r"name",
    r"e-?mail",
    r"phone",
    r"address",
    r"birth",
    r"\bdob\b",
    r"\bssn\b",
)

CHART_MIN_R = 0.3
CHART_PEOPLE_PER_PAGE = 200
