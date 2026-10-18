# Run with the project venv active, with the ai extra installed so the language model providers
# are bundled (pip install -e ".[ai]"), and give -Out a folder outside the repository; the program
# goes to <Out>/labcatalog/ and PyInstaller's working files to <Out>/build/.
# The scientific packages go in whole, since the program also runs the lab's Python scripts.
# PyInstaller itself, as nicegui-pack does, since nicegui-pack passes on no further options.
param([string]$Out = "dist")
# The spec file sits in <Out>/build, so every path given is absolute.
$repo = (Split-Path $PSScriptRoot).Replace("\", "/")
$nicegui = python -c "import nicegui, pathlib; print(pathlib.Path(nicegui.__file__).parent)"
pyinstaller --distpath "$Out" --workpath "$Out/build" --specpath "$Out/build" --onedir --windowed --noconfirm --name labcatalog --add-data "$nicegui;nicegui" --icon "$repo/src/labcatalog/gui/assets/icon.ico" --add-data "$repo/src/labcatalog/blank.yaml;labcatalog" --add-data "$repo/src/labcatalog/example;labcatalog/example" --add-data "$repo/src/labcatalog/gui/theme.css;labcatalog/gui" --add-data "$repo/src/labcatalog/gui/network_graph.js;labcatalog/gui" --add-data "$repo/src/labcatalog/gui/banner_art.js;labcatalog/gui" --add-data "$repo/src/labcatalog/gui/assets;labcatalog/gui/assets" --add-data "$repo/src/labcatalog/gui/vendor;labcatalog/gui/vendor" --add-data "$repo/src/labcatalog/stats/cfa.R;labcatalog/stats" --add-data "$repo/src/labcatalog/stats/invariance.R;labcatalog/stats" --add-data "$repo/src/labcatalog/vocabularies;labcatalog/vocabularies" --collect-submodules pandas --collect-submodules numpy --collect-submodules scipy --collect-submodules statsmodels --collect-submodules semopy --collect-all matplotlib "$repo/packaging/app.py"
