from labcatalog import defaults
from labcatalog.metadata import accepted
from labcatalog.pipeline import run_check, run_validate


def test_an_accepted_warning_is_hidden_until_withdrawn(mock_project):
    report = run_check(mock_project)
    warning = next(i for i in report.issues if i.code == "same_answer")
    accepted.accept(mock_project, warning, "Checked the paper forms: they did answer that way")
    again = run_check(mock_project)
    assert warning not in again.issues and again.accepted == [warning]
    [entry] = accepted.load(mock_project, [])
    assert entry.reason.startswith("Checked") and entry.by
    accepted.withdraw(mock_project, warning)
    assert warning in run_check(mock_project).issues


def test_errors_are_never_hidden(mock_project):
    error = next(i for i in run_check(mock_project).issues if i.level == "error")
    accepted.accept(mock_project, error, "no")
    assert error in run_check(mock_project).issues


def test_a_broken_file_is_reported(mock_project):
    (mock_project / defaults.ACCEPTED_FILENAME).write_text("accepted: [{code: x}]\n", "utf-8")
    found = [i for i in run_validate(mock_project) if i.location == defaults.ACCEPTED_FILENAME]
    assert found and all(i.level == "error" for i in found)
