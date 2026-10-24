import json
import os
import time
from pathlib import Path

import pytest
import yaml

from labcatalog.codebook.derivatives import Request, run_derivatives, table_step
from labcatalog.data.check import check_values
from labcatalog.data.prepare import Session, run_steps, step_states
from labcatalog.data.resolve import Catalog, resolve_catalog
from labcatalog.exceptions import CodebookError
from labcatalog.gui.pipeline_table import PipelineForm, changed, form_of, missing, request_of
from labcatalog.metadata import changes
from labcatalog.metadata.scripts import step_change
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project
from labcatalog.sources import load_dataset

ROWS = [
    "bids_name\tsci\tsnr\tdevice",
    "sub-01_ses-01_task-rest_nirs\t0.9\t12\tA",
    "sub-01_ses-01_task-nback_nirs\t0.8\tn/a\tA",
    "sub-02_ses-01_task-rest_nirs\t0.7\t9\tB",
    "sub-01_ses-02_task-rest_nirs\t0.95\t14\tA",
]
SIDECAR = {
    "sci": {"LongName": "Mean SCI", "Description": "Scalp coupling index."},
    "snr": {"Description": "Signal to noise.", "Units": "dB"},
}


def pipeline_table(root: Path, rows: list[str] = ROWS) -> Path:
    folder = root / "derivatives" / "pipe"
    folder.mkdir(parents=True)
    (folder / "dataset_description.json").write_text(
        json.dumps({"Name": "pipe output", "GeneratedBy": [{"Name": "pipe", "Version": "1.2"}]})
    )
    (folder / "desc-qc.json").write_text(json.dumps(SIDECAR))
    table = folder / "desc-qc.tsv"
    table.write_text("\n".join(rows) + "\n")
    return table


def request(table: Path, **changes) -> Request:
    fields = {"name": "qc", "study": "demo_study", "modality": "fnirs", "reporter": "child"}
    return Request(table, **(fields | changes))


def test_writes_an_instrument_per_task_and_a_data_file_per_session(demo_project):
    table = pipeline_table(demo_project)
    done = run_derivatives(demo_project, request(table, split=["task"]))
    assert done.left_out == ["device"]
    rest = yaml.safe_load((demo_project / "instruments" / "qc_rest.yaml").read_text())
    assert rest["modality"] == "fnirs" and rest["description"] == "Measures from pipe 1.2 for rest."
    assert rest["items"] == [
        {"id": "sci", "label": "Mean SCI", "text": "Scalp coupling index.", "type": "number"},
        {"id": "snr", "text": "Signal to noise. (dB)", "type": "number"},
    ]
    first = (demo_project / "data" / "qc_w1.csv").read_text().splitlines()
    assert first[0].split(",")[1:] == ["nback_sci", "nback_snr", "rest_sci", "rest_snr"]
    assert first[1:] == ["sub-01,0.8,,0.9,12", "sub-02,,,0.7,9"]
    assert (demo_project / "maps" / "qc_w2.csv").read_text().splitlines()[3] == (
        "nback_snr,qc_nback,snr"
    )
    steps = dict(done.steps)
    assert list(steps) == [
        "In labcatalog.yaml, add under studies, demo_study, waves:",
        "In labcatalog.yaml, add under datasets:",
        "In studies/demo_study.yaml, add under administrations:",
    ]
    assert steps["In labcatalog.yaml, add under studies, demo_study, waves:"] == "  2: {}"
    assert (
        "{name: qc_w2, modality: fnirs, study: demo_study, wave: 2, reporter: child"
        in (steps["In labcatalog.yaml, add under datasets:"])
    )


def test_the_printed_lines_make_a_valid_project(demo_project):
    table = pipeline_table(demo_project)
    done = run_derivatives(demo_project, request(table, split=["task"]))
    config = demo_project / "labcatalog.yaml"
    steps = list(dict(done.steps).values())
    data = yaml.safe_load(config.read_text())
    data["studies"]["demo_study"]["waves"] |= yaml.safe_load(steps[0])
    data["datasets"] += yaml.safe_load(steps[1])
    data["vocab"]["modalities"].append("fnirs")
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    study = next((demo_project / "studies").glob("*.yaml"))
    content = yaml.safe_load(study.read_text())
    content["administrations"] += yaml.safe_load(steps[2])
    study.write_text(yaml.safe_dump(content, sort_keys=False))
    issues = validate_project(load_project(demo_project))
    assert [i for i in issues if i.level == "error"] == []
    assert run_derivatives(demo_project, request(table, split=["task"])).steps == []


def test_running_again_keeps_what_the_user_changed(demo_project):
    table = pipeline_table(demo_project)
    run_derivatives(demo_project, request(table, columns=["sci"], split=["task"]))
    path = demo_project / "instruments" / "qc_rest.yaml"
    edited = yaml.safe_load(path.read_text())
    edited["name"] = "Resting quality"
    edited["items"][0]["text"] = "My wording."
    path.write_text(yaml.safe_dump(edited, sort_keys=False))
    run_derivatives(demo_project, request(table, split=["task"]))
    again = yaml.safe_load(path.read_text())
    assert again["name"] == "Resting quality"
    assert [i["id"] for i in again["items"]] == ["sci", "snr"]
    assert again["items"][0]["text"] == "My wording."


def test_rows_that_repeat_name_the_entity_to_split_by(demo_project):
    table = pipeline_table(demo_project)
    with pytest.raises(
        CodebookError, match="Several rows for sub-01 in wave 1; split them by task"
    ):
        run_derivatives(demo_project, request(table))


def test_a_table_without_sessions_needs_a_wave(demo_project):
    rows = ["participant_id\tage", "sub-01\t30", "sub-02\t41"]
    table = pipeline_table(demo_project, rows)
    with pytest.raises(CodebookError, match="give the Wave"):
        run_derivatives(demo_project, request(table))
    run_derivatives(demo_project, request(table, wave="1"))
    assert (demo_project / "data" / "qc_w1.csv").read_text().splitlines() == [
        "id,age",
        "sub-01,30",
        "sub-02,41",
    ]
    assert (demo_project / "maps" / "qc_w1.csv").read_text().splitlines()[2] == "age,qc,age"
    assert yaml.safe_load((demo_project / "instruments" / "qc.yaml").read_text())["items"] == [
        {"id": "age", "text": "age", "type": "number"}
    ]


def test_the_import_page_form_asks_for_what_is_missing_and_splits_lists():
    form = PipelineForm(table="t.tsv", name=" qc ", study="s", modality="fnirs")
    assert missing(form) == ["the reporter"]
    form.reporter, form.split, form.columns = "self", "task, run", "raw_* motion_*"
    made = request_of(form)
    assert (made.name, made.split, made.columns, made.wave) == (
        "qc",
        ["task", "run"],
        ["raw_*", "motion_*"],
        None,
    )


def test_a_column_with_levels_is_a_choice_with_its_own_options(demo_project):
    rows = [
        f"{row}	{value}" for row, value in zip(ROWS, ["usable", 1, 0, 1, "n/a"], strict=True)
    ]
    table = pipeline_table(demo_project, rows)
    levels = {"Levels": {"0": "no", "1": "yes"}, "Description": "Usable run."}
    (table.parent / "desc-qc.json").write_text(json.dumps({**SIDECAR, "usable": levels}))
    done = run_derivatives(demo_project, request(table, split=["task"]))
    assert done.left_out == ["device"]
    found = yaml.safe_load((demo_project / "instruments" / "qc_rest.yaml").read_text())
    assert found["response_sets"] == [
        {"id": "usable", "options": [{"value": 0, "label": "no"}, {"value": 1, "label": "yes"}]}
    ]
    assert found["items"][-1] == {"id": "usable", "text": "Usable run.", "response_set": "usable"}
    # Running again keeps a set the user renamed and adds none twice.
    path = demo_project / "instruments" / "qc_rest.yaml"
    found["response_sets"][0]["options"][1]["label"] = "kept"
    path.write_text(yaml.safe_dump(found))
    run_derivatives(demo_project, request(table, split=["task"]))
    again = yaml.safe_load(path.read_text())
    assert [o["label"] for o in again["response_sets"][0]["options"]] == ["no", "kept"]
    assert len(again["response_sets"]) == 1


def test_sidecars_higher_in_the_tree_describe_the_tables_below(demo_project):
    folder = demo_project / "derivatives" / "pipe"
    nested = folder / "sub-01" / "ses-01"
    nested.mkdir(parents=True)
    (folder / "dataset_description.json").write_text(json.dumps({"Name": "pipe"}))
    (folder / "qc.json").write_text(json.dumps(SIDECAR))
    (folder / "task-rest_qc.json").write_text(json.dumps({"snr": {"Description": "Rest SNR."}}))
    (folder / "task-nback_qc.json").write_text(json.dumps({"snr": {"Description": "Wrong."}}))
    table = nested / "sub-01_ses-01_task-rest_qc.tsv"
    table.write_text("participant_id\tsession_id\tsci\tsnr\nsub-01\tses-01\t0.9\t12\n")
    run_derivatives(demo_project, request(table))
    found = yaml.safe_load((demo_project / "instruments" / "qc.yaml").read_text())
    assert [i["text"] for i in found["items"]] == ["Scalp coupling index.", "Rest SNR."]


def test_a_choice_from_levels_checks_its_values(demo_project):
    rows = [f"{row}\t{value}" for row, value in zip(ROWS, ["usable", 1, 0, 2, "n/a"], strict=True)]
    table = pipeline_table(demo_project, rows)
    levels = {"Levels": {"0": "no", "1": "yes"}}
    (table.parent / "desc-qc.json").write_text(json.dumps({**SIDECAR, "usable": levels}))
    done = run_derivatives(demo_project, request(table, split=["task"]))
    config = demo_project / "labcatalog.yaml"
    steps = list(dict(done.steps).values())
    data = yaml.safe_load(config.read_text())
    data["studies"]["demo_study"]["waves"] |= yaml.safe_load(steps[0])
    data["datasets"] += yaml.safe_load(steps[1])
    data["vocab"]["modalities"].append("fnirs")
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    study = next((demo_project / "studies").glob("*.yaml"))
    content = yaml.safe_load(study.read_text())
    content["administrations"] += yaml.safe_load(steps[2])
    study.write_text(yaml.safe_dump(content, sort_keys=False))
    project = load_project(demo_project)
    assert [i for i in validate_project(project) if i.level == "error"] == []
    loaded = {
        d.name: load_dataset(project, d) for d in project.config.datasets if d.modality == "fnirs"
    }
    catalog = resolve_catalog(project)
    mine = [v for v in catalog.variables if v.dataset in loaded]
    issues = check_values(project, Catalog(variables=mine, scores=[]), loaded)
    # Only the 2, which is no level, is reported.
    assert [(i.code, i.details["column"]) for i in issues] == [("unexpected_value", "rest_usable")]


def registered(root: Path) -> Path:
    # The project with the table's datasets added, as the printed lines say.
    table = pipeline_table(root)
    asked = request(table, split=["task"])
    done = run_derivatives(root, asked)
    config = root / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text())
    steps = list(dict(done.steps).values())
    data["studies"]["demo_study"]["waves"] |= yaml.safe_load(steps[0])
    data["datasets"] += yaml.safe_load(steps[1])
    data["vocab"]["modalities"].append("fnirs")
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    study = next((root / "studies").glob("*.yaml"))
    content = yaml.safe_load(study.read_text())
    content["administrations"] += yaml.safe_load(steps[2])
    study.write_text(yaml.safe_dump(content, sort_keys=False))
    project = load_project(root)
    changes.write(project, [step_change(project, None, table_step(asked, root, done))])
    return table


def test_a_kept_table_step_takes_the_table_in_again_when_it_is_rewritten(demo_project):
    table = registered(demo_project)
    project = load_project(demo_project)
    [step] = [s for s in project.config.prepare if s.table is not None]
    assert step.name == "table_qc" and step.run == "" and step.stage == "extract"
    assert step.table.path == "derivatives/pipe/desc-qc.tsv"
    assert step.inputs == ["derivatives/pipe/desc-qc.tsv", "derivatives/pipe/desc-qc.json"]
    assert step.outputs == ["data/qc_w1.csv", "data/qc_w2.csv"]
    assert "table:" in (demo_project / "labcatalog.yaml").read_text()
    assert [s.status for s in step_states(project) if s.step.name == step.name] == ["up to date"]
    later = time.time() + 5
    table.write_text("\n".join([*ROWS, "sub-03_ses-01_task-rest_nirs\t0.6\t8\tC"]) + "\n")
    os.utime(table, (later, later))
    [state] = [s for s in step_states(project) if s.step.name == step.name]
    assert state.status == "outdated"
    [run] = run_steps(project, [step.name], Session(), outdated_only=True)
    assert run.exit_code == 0 and "Wrote data/qc_w1.csv" in run.log
    assert "sub-03" in (demo_project / "data" / "qc_w1.csv").read_text()
    assert [i for i in validate_project(load_project(demo_project)) if i.level == "error"] == []


def test_a_table_steps_settings_open_as_the_form_and_a_change_is_seen(demo_project):
    registered(demo_project)
    [step] = [s for s in load_project(demo_project).config.prepare if s.table is not None]
    form = form_of(step.table, demo_project)
    assert form.split == "task" and form.reporter == "child"
    assert not changed(form, step.table, demo_project)
    form.columns = "sci"
    assert changed(form, step.table, demo_project)


def test_a_table_step_that_fails_says_why(demo_project):
    table = registered(demo_project)
    table.write_text("nothing\there\n")
    project = load_project(demo_project)
    [run] = run_steps(project, ["table_qc"], Session())
    assert run.exit_code == 1 and "bids_name" in run.log[-1]


def test_a_step_needs_a_command_or_a_table_but_not_both(demo_project):
    registered(demo_project)
    config = demo_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text())
    data["prepare"][-1]["run"] = "python x.py"
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    messages = [i.message for i in validate_project(load_project(demo_project))]
    assert any("not both" in m for m in messages)
    del data["prepare"][-1]["run"], data["prepare"][-1]["table"]
    config.write_text(yaml.safe_dump(data, sort_keys=False))
    messages = [i.message for i in validate_project(load_project(demo_project))]
    assert any("the command is empty" in m for m in messages)
