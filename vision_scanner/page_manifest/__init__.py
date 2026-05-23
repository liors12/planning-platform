"""Per-page vision manifest (M1).

Rasterizes each requested page of an architect submission PDF and asks
Gemini Flash to produce a structured PageManifest describing what's on
the page. Feeds M2's unified extraction pass.
"""
