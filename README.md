# labcatalog

labcatalog builds a browsable catalog of a lab's study data. You describe your instruments, studies and data files in a few YAML files, point it at your cleaned data, and it gives you a desktop window where you can browse every instrument and variable across waves, see where the data disagree with the metadata, run the analyses most papers need, and copy the results as tables and text into a manuscript.

It works with questionnaires and with features from other modalities (EEG, fMRI, eye tracking, physiological measures and others), and it does not assume any particular lab, study design or discipline.

## Install

labcatalog needs Python 3.11 or newer.

```bash
uv tool install "git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

or, with pip in an environment of your choice:

```bash
pip install "git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

## Try it

```bash
labcatalog init my_example
labcatalog gui -p my_example
```

`labcatalog init` copies a fictional example project into a new folder; `labcatalog gui` opens it.

## Documentation

The handbook is in [docs/](docs/). To read it locally:

```bash
pip install "labcatalog[docs] @ git+https://github.com/AU-CONNECT-Lab/labcatalog"
cd docs
jupyter-book start
```

## License

Apache-2.0. See [LICENSE](LICENSE).
