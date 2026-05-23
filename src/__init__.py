"""src package marker — lets `python -m src.pdf` resolve from the repo root.

Internal modules use bare imports like `from compliance.types import …` and
rely on `src/` being on sys.path. The CLI entry point (`src/pdf/__main__.py`)
self-bootstraps by inserting that directory before its first internal import.
"""
