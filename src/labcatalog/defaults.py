SCHEMA_VERSION = 1

CONFIG_FILENAME = "labcatalog.yaml"
YAML_SUFFIXES = (".yaml", ".yml")
INSTRUMENTS_DIR = "instruments"
STUDIES_DIR = "studies"
MAPS_DIR = "maps"
SCORE_PREFIX = "score:"

ID_COLUMN = "id"
DATE_FORMAT = "%Y-%m-%d"
BLANK_LABEL = "blank"
MIN_CORRELATION_N = 3
CORRELATE_BY = "id"
SAME_ANSWER_MIN_ITEMS = 5
DEFAULT_MODALITIES = ("questionnaire",)

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
