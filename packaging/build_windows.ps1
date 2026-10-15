# Run from the repository root with the project venv active; output goes to dist\labcatalog\.
nicegui-pack --onedir --windowed --noconfirm --name labcatalog --add-data "src/labcatalog/gui/theme.css;labcatalog/gui" packaging/app.py
