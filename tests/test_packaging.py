import re
from pathlib import Path

REPO = Path(__file__).parents[1]
PACKAGE = REPO / "src" / "labcatalog"


def bundled() -> dict[Path, str]:
    text = (REPO / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    pairs = re.findall(r'--add-data "([^;"]+);([^"]+)"', text)
    return {REPO / source: target for source, target in pairs}


def test_the_windows_program_bundles_every_file_the_package_reads_where_the_code_looks():
    added = bundled()
    for source, target in added.items():
        assert source.exists(), source
        where = source.relative_to(REPO / "src")
        assert target == (where if source.is_dir() else where.parent).as_posix()
    # Python files are bundled as code, except the example project's, which are its data.
    needed = [
        path
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.suffix != ".py" or (PACKAGE / "example") in path.parents)
    ]
    missing = [
        path.relative_to(REPO).as_posix()
        for path in needed
        if not any(path == source or source in path.parents for source in added)
    ]
    assert not missing
