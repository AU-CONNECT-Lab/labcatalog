SCHEMA_VERSION = 1

CONFIG_FILENAME = "labcatalog.yaml"
YAML_SUFFIXES = (".yaml", ".yml")
INSTRUMENTS_DIR = "instruments"
STUDIES_DIR = "studies"
MAPS_DIR = "maps"
SCHEMAS_DIR = "schemas"
SCORE_PREFIX = "score:"

ID_COLUMN = "id"
DATE_FORMAT = "%Y-%m-%d"
BLANK_LABEL = "blank"
MIN_CORRELATION_N = 3
CORRELATE_BY = "id"
SAME_ANSWER_MIN_ITEMS = 5
DEFAULT_MODALITIES = ("questionnaire",)
BUILTIN_FACETS = ("study", "wave", "reporter", "target", "modality")
DEFAULT_FACETS = ("study", "wave", "reporter")
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
