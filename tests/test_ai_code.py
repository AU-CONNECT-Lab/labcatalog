import pytest

from conftest import rscript
from labcatalog.ai.code import syntax_error

needs_r = pytest.mark.skipif(rscript() is None, reason="R is not installed")


def test_python_that_does_not_parse_gives_the_line():
    split = "def f(d):\n    keep = d.a == 1 &\n        d.b == 2\n    return keep\n"
    assert syntax_error(split, "python", None) == 'Line 2: invalid syntax (in "keep = d.a == 1 &")'
    assert syntax_error("x = (1,\n", "python", None).startswith("Line 1: '(' was never closed")
    assert syntax_error("x = 1\n", "python", None) == ""


@needs_r
def test_r_that_does_not_parse_gives_the_line():
    text = "R Script:\nx <- 1\n"
    assert syntax_error(text, "r", rscript()) == 'Line 1: unexpected symbol (in "R Script:")'
    unclosed = "f <- function(a) {\n  a + 1\n"
    assert syntax_error(unclosed, "r", rscript()) == "Line 3: unexpected end of input"
    assert syntax_error('# d′\nx <- "café"\n', "r", rscript()) == ""


def test_r_goes_unchecked_without_rscript():
    assert syntax_error("R Script:\n", "r", None) == ""
