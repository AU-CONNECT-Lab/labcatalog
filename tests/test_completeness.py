from labcatalog.completeness import gaps
from labcatalog.schema import Instrument, Item, Reference, Score


def test_a_bare_questionnaire_lacks_everything_after_its_items():
    bare = Instrument(id="q", name="Q", items=[Item(id="q_1", text="How?")])
    assert gaps(bare) == [
        "construct",
        "description",
        "scores",
        "reference",
        "reference PDF",
        "license",
    ]


def test_a_full_questionnaire_lacks_nothing():
    full = Instrument(
        id="q",
        name="Q",
        construct_name="Mood",
        description="It asks about mood.",
        items=[Item(id="q_1", text="How?")],
        scores=[Score(id="q_total", label="Total", method="sum", items=["q_1"])],
        references=[Reference(key="q2020", pdf="q.pdf")],
        license="Free for research",
    )
    assert gaps(full) == []
    full.references = [Reference(key="q2020")]
    assert gaps(full) == ["reference PDF"]


def test_demographics_and_other_modalities_need_less():
    assert gaps(Instrument(id="d", name="D", kind="demographics")) == ["items"]
    measure = Instrument(id="e", name="E", kind="eeg", items=[Item(id="alpha", text="Alpha")])
    assert gaps(measure) == ["construct", "description"]
