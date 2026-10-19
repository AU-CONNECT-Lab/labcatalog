# Scripts

The Scripts page holds every script of the project in one place: the scripts the [prepare steps](prepare.md) run, the analyses kept from the Custom tab of the [Analysis](analysis.md) page, and any other R or Python file in `scripts/` or `analyses/`. **Script** beside a step in the **Add data** step of the Set up page opens its script here.

## The list

The scripts are listed on the left in three groups; click one to open it.

- **Prepare steps**: each script a step runs, found in the step's command or its inputs. One script can be run by several steps, such as one cleaning script for every wave; hover over it to see how many. A step whose command names no script of the project, such as a command of its own program, is listed by its name.
- **Analyses**: the scripts listed under `analyses` in `labcatalog.yaml`.
- **Not run**: R and Python files in `scripts/` and `analyses/` that nothing runs yet.

## A script

The top shows the script's code with its syntax coloured. Change it there and press **Save**, or press **Open in your editor** to edit it in the program your computer opens it with. Saving a script puts the steps that run it out of date, since the script is one of their inputs. Choosing another script with unsaved changes asks first.

For a script that steps run, **Steps that run it** lists them as on the Add data step, each with its status, command, inputs and outputs, **Run** and **Log**, and two more buttons:

- **Edit** changes the step's name, command, inputs and outputs. The command runs in the project folder; a file it reads is an input and a file it writes is an output, and every step writes at least one.
- **Remove** takes the step out of `labcatalog.yaml`. The script and the files stay.

**Add a step** adds a step that runs the script, starting from a command such as `Rscript scripts/tidy.R INPUT OUTPUT` for you to fill in. A step is checked before it is written, and refused if it would cause a problem, such as a step that writes its own input. Below the steps, the **Log** shows what the last step printed.

For an analysis, the panel shows what was asked for, its datasets and variables, and **Delete**, which deletes the script and its entry under `analyses`. It runs on the Custom tab.

## New scripts

**New script** writes a new R or Python file in `scripts/`, named with lower-case letters, digits and `_`, with the lines that read its input file and write its output file, the two arguments a step's command gives it. Give it a step with **Add a step**.

**Draft a cleaning step**, at the bottom of the page, has a language model write a cleaning script for a dataset; see [Register Prepare Steps](../how-to/prepare-steps.md#draft-a-step-with-a-language-model).
