"""Phase 7.1 — CAD ingest pipeline (narrowed slice).

Provides the takanon-side authoritative plot dataset (polygons + land-use codes +
canonical areas) derived from the planning authority's DWG tashrit files. The
slice deliverable is a plot-completeness finding for plots 6, 7, 8, 9, 10, 20 —
plots the architect didn't include in the v24.3 submission but are statutorily
part of the תב"ע.

Module layout:
  oda_wrapper.py         — subprocess wrapper around ODA File Converter
  dxf_reader.py          — ezdxf + shapely extraction of plot polygons
  takanon_dataset.py     — orchestrates DWG→DXF→dataset; CODE descriptions
  plot_completeness.py   — produces M4-compatible cad_evidence finding
"""
