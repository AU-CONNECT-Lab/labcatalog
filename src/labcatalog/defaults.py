SCHEMA_VERSION = 1

CONFIG_FILENAME = "labcatalog.yaml"
YAML_SUFFIXES = (".yaml", ".yml")
INSTRUMENTS_DIR = "instruments"
STUDIES_DIR = "studies"
MAPS_DIR = "maps"
SCORE_PREFIX = "score:"
OUTPUT_DIR = "site"
MANIFEST_FILENAME = "manifest.json"

ID_COLUMN = "id"
DATE_FORMAT = "%Y-%m-%d"
DEFAULT_MODALITIES = ("questionnaire",)

REFERENCES_MODE = "link"
REFERENCES_ROUTE = "/_refs/"
PREVIEW_PORT = 8000

ID_CHANGE_EXAMPLES = 5
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
