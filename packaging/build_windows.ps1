# Run from the repository root with the project venv active, with the ai extra installed so the
# language model providers are bundled (pip install -e ".[ai]"); output goes to dist\labcatalog\.
nicegui-pack --onedir --windowed --noconfirm --name labcatalog --icon src/labcatalog/gui/assets/icon.ico --add-data "src/labcatalog/gui/theme.css;labcatalog/gui" --add-data "src/labcatalog/gui/assets;labcatalog/gui/assets" packaging/app.py
