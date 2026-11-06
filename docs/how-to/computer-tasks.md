# Record a Computer Task

A computer task such as an N-back, run in PsychoPy or E-Prime, saves a file of trials for each person. labcatalog keeps two datasets for it: the trial files themselves, counted as a folder dataset, and one row of measures per person, which a script computes from the files. The example project has one, a letter N-back that 15 children did at wave 2, and this page follows it.

## The trial files

PsychoPy saves each run as a CSV file named after the participant, the experiment and the time it started, such as `1007C_nback_2025-03-07_10h26.08.702.csv`, with a row for each trial: the loop counters, the letter shown, whether it was a target, the key pressed, whether that was correct and the response time. Practice trials are rows too, with the main loop's counters left blank.

E-Prime saves `.edat2` files, which only E-Prime's own programs read. Open them in E-DataAid and export them as tab-delimited text first. A file merged with E-Merge holds everyone, so its step reads that one file, as `extract_saliva` reads one assay report in the example, rather than a folder.

Put the files in the project, such as under `raw/nback/ses-2/`, and add `task`, or a word of your own, to the modalities:

```yaml
vocab:
  modalities: [questionnaire, eeg, fmri, fnirs, eyetracking, video, ecg, saliva, actigraphy, task]
  modality_labels: {task: computer tasks}
```

Then add the folder as a dataset with **Add a dataset** on the [Datasets](../app/datasets.md#add-a-dataset) page. For PsychoPy's names the window suggests `{id}_nback_*_*.csv`, where the date and the time match anything:

```yaml
datasets:
  - {name: nback_trials_w2, modality: task, study: mock_study, wave: 2, reporter: child, source: folder, path: raw/nback/ses-2, files: '{id}_nback_*_*.csv'}
```

The dataset counts who did the task in each wave, and the Problems page checks its IDs against the roster and the ID pattern, before any measure is computed.

## The measures

An extract script turns each person's file into their row. The example's `scripts/extract_nback_w2.py` keeps the lines an extract script from **New script** starts with (see [Scripts](../app/scripts.md#new-scripts)), with `FILES` set to the dataset's rule, and fills in `features()`: it drops the practice rows, and for each block gives the share of trials answered correctly, the mean response time of correct trials and d′, leaving a block blank when the child answered fewer than 30 of its 40 trials. Its step writes the dataset `nback_w2`:

```yaml
prepare:
  - {name: extract_nback_w2, run: python scripts/extract_nback_w2.py raw/nback/ses-2 data/nback_w2.csv, inputs: [raw/nback/ses-2, scripts/extract_nback_w2.py], outputs: [data/nback_w2.csv], stage: extract}
datasets:
  - {name: nback_w2, modality: task, study: mock_study, wave: 2, reporter: child, source: csv, path: data/nback_w2.csv, date_column: visit_date}
```

With a folder among a step's inputs, the step is outdated when any file in it is newer than the output. The measures are the items of an instrument, `instruments/nback.yaml`, each a number with the range it can take, as for the other modalities ([Instruments](../concepts/instruments.md)):

```yaml
id: nback
name: Letter N-back task
modality: task
construct_name: Working memory
items:
  - {id: acc_1back, label: "1-back accuracy", text: "Share of 1-back trials answered correctly", type: number, min: 0, max: 1}
  - {id: dprime_2back, label: "2-back d′", text: "Sensitivity d′ in the 2-back block, from hits and false alarms", type: number, min: -5, max: 5}
```

`maps/nback_w2.csv` maps each column to its item, and the study's administrations list `nback_w2` under `nback`. The measures are then analysis variables like any others; on the [Analysis](../app/analysis.md) page, for example, **Paired** compares d′ in the 1-back and 2-back blocks.

## Draft the measures with a language model

With a language model set on the Settings page (see [Set Up R and Language Models](r-and-models.md)), **Draft a summary step** at the bottom of the [Scripts](../app/scripts.md) page writes `features()` and drafts the instrument for you. Choose the folder dataset under **Files**, name the **Dataset it writes**, give the **Instrument ID** and say under **Measures to compute** what to compute, such as "accuracy, mean response time of correct trials and d′ for each block", then choose R or Python and press **Draft**.

The model is given the dataset's rule, modality, study, wave and reporter, the measures you asked for, and its files' column names with, as the Settings page sets, either each column's different values across all its files (so a value only some people have, such as PsychoPy's `None` for a trial with no key press, is there too), or the first 20 lines of its largest file, likely a full session rather than one cut short. It returns `features()`, the instrument's name and construct, and an item for each measure the function returns. The script, the instrument draft and the model's notes open in a window, and nothing is written until you press **Save**. A script that does not parse (an R script only when Rscript is set on the Settings page) is marked there with the line it fails at. Saving writes:

- `scripts/extract_<dataset>.R` or `.py`: an extract script with the model's `features()` and the dataset's rule as `FILES`, which writes `data/<dataset>.csv`, or the file of the dataset of that name if it is already added.
- The step `extract_<dataset>`, with the folder and the script as inputs.
- `drafts/<instrument>.yaml`, replacing a draft of the same ID, with each measure as a number item and the folder dataset's modality.

Then run the step on the Scripts page and look at its file; open the draft on the [Edit](../app/edit.md) page, check it against the script and press **Move to instruments**; and add the file with **Add a dataset**, mapping its columns to the instrument's items.
