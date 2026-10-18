"""Draw the overview banner's star map from the example catalog; the look is set in banner.html."""

import argparse
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

import labcatalog
from labcatalog.charts import views
from labcatalog.pipeline import run_catalog

HERE = Path(__file__).parent
OUTPUT = Path(labcatalog.__file__).parent / "gui" / "assets" / "banner.svg"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run from the repository root; d3 loads from cdnjs."
    )
    parser.add_argument("--chrome", default=CHROME)
    parser.add_argument("--keep-html", action="store_true", help="also write banner_preview.html")
    args = parser.parse_args()

    example = Path(labcatalog.__file__).parent / "example"
    result = run_catalog(example)
    spec = views.catalog_map(result, list(result.project.instruments))
    page = (HERE / "banner.html").read_text(encoding="utf-8").replace("__SPEC__", json.dumps(spec))
    with tempfile.TemporaryDirectory() as folder:
        built = Path(folder) / "banner.html"
        built.write_text(page, encoding="utf-8")
        dom = subprocess.run(
            [
                args.chrome,
                "--headless=new",
                "--disable-gpu",
                "--virtual-time-budget=15000",
                "--dump-dom",
                built.as_uri(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
    found = re.search(r'<pre id="art" hidden="">(.*?)</pre>', dom, re.S)
    if found is None:
        raise SystemExit("The page drew nothing; is cdnjs reachable?")
    OUTPUT.write_text(html.unescape(found.group(1)), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")
    if args.keep_html:
        (HERE / "banner_preview.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
