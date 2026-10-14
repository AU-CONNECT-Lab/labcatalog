import pandas as pd

from labcatalog.ids import family_ids


def test_family_from_id():
    family = family_ids(pd.Series(["1001P", "1001C", "x"]), r"^(\d{4})")
    assert family.tolist()[:2] == ["1001", "1001"]
    assert pd.isna(family.iloc[2])
