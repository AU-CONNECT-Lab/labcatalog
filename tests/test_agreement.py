import shutil
from glob import glob

import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import agreement, analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.agreement import Agreement, IccRow, KappaPair

CHILD, PARENT = "child_w1", "parent_child_w1"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


needs_r = pytest.mark.skipif(rscript() is None, reason="R is not installed")


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, [CHILD, PARENT], True)


def item_raters(result, sample):
    # The child and the parent rating the child on the same item.
    found = agreement.choices(result, sample.datasets, {n: n for n in sample.datasets})
    return [k for k in found if ".ewt_1@" in k]


def test_answer_options_give_kappa_and_scores_give_intraclass_correlations(result, sample):
    data = script.AnalysisData(result, sample)
    items = [data.variable(k) for k in item_raters(result, sample)]
    assert [v.kind for v in items] == [script.CHOICE] * 2
    assert agreement.kind_of(items) == agreement.KAPPA
    totals = [data.variable(f"example_worries_temper.ewt_total@{n}") for n in (CHILD, PARENT)]
    assert agreement.kind_of(totals) == agreement.ICC
    assert agreement.agreement_code(totals).outputs == ("icc",)


@needs_r
def test_kappa_is_the_same_in_r_and_python(result, sample):
    data = script.AnalysisData(result, sample)
    items = [data.variable(k) for k in item_raters(result, sample)]
    frame = data.frame()
    code = agreement.agreement_code(items)
    found_r, _ = script.run_code(result, sample, frame, code, rscript())
    found_python, _ = script.run_code(result, sample, frame, code, None)
    [r_pair] = agreement.read_agreement(found_r, items).kappas
    [python_pair] = agreement.read_agreement(found_python, items).kappas
    assert r_pair.n == python_pair.n == frame[[v.column for v in items]].dropna().shape[0]
    for name in ("kappa", "kappa_low", "kappa_high", "weighted", "weighted_low"):
        assert getattr(r_pair, name) == pytest.approx(getattr(python_pair, name), abs=1e-9)
    assert r_pair.kappa_low < r_pair.kappa < r_pair.kappa_high


@needs_r
def test_intraclass_correlations_use_everyone_with_a_rating(result, sample):
    data = script.AnalysisData(result, sample)
    totals = [data.variable(f"example_worries_temper.ewt_total@{n}") for n in (CHILD, PARENT)]
    frame = data.frame()
    found, _ = script.run_code(result, sample, frame, agreement.agreement_code(totals), rscript())
    found_agreement = agreement.read_agreement(found, totals)
    assert found_agreement.n == frame[[v.column for v in totals]].dropna(how="all").shape[0]
    assert [r.type for r in found_agreement.icc] == list(agreement.ICC_TYPES)
    assert all(r.low < r.icc < r.high for r in found_agreement.icc)


def test_the_paragraph_names_the_icc_or_the_kappas():
    icc = Agreement(
        agreement.ICC,
        2,
        n=50,
        icc=[
            IccRow("ICC2", 0.712, 0.55, 0.82, 6.0, 49, 49, 0.0),
            IccRow("ICC2k", 0.832, 0.71, 0.9, 6.0, 49, 49, 0.0),
        ],
    )
    assert results.agreement_text(icc) == (
        "Agreement between the two raters, on the 50 people rated by either, was ICC(2,1) = .71, "
        "95% CI [.55, .82] (two-way random effects, absolute agreement, single rater); for the "
        "mean of the raters, ICC(2,k) = .83, 95% CI [.71, .90]."
    )
    pairs = [
        KappaPair("a", "b", 40, 0.6, None, None, None, None, None),
        KappaPair("a", "c", 40, 0.4, None, None, None, None, None),
        KappaPair("b", "c", 40, 0.2, None, None, None, None, None),
    ]
    assert results.agreement_text(Agreement(agreement.KAPPA, 3, kappas=pairs)) == (
        "Cohen's κ averaged over the 3 pairs of the 3 raters (Light's κ) was .40, ranging from "
        ".20 to .60 across pairs."
    )
