from labcatalog.resolve import Catalog, ResolvedScore


def score_code_r(score: ResolvedScore) -> str:
    raise NotImplementedError


def score_code_python(score: ResolvedScore) -> str:
    raise NotImplementedError


def scoring_snippets(catalog: Catalog) -> dict[str, dict[str, str]]:
    raise NotImplementedError
