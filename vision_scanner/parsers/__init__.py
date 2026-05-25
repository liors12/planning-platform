"""Top-level parsers package for vision_scanner.

Modules here are pure post-processors over already-extracted M1/M2 data —
no LLM calls, no PDF rasterization. They surface latent signals (amenity
inventory, ground-reference cross-checks, etc.) that don't require new
extraction.
"""
