"""M2 unified extraction: 63 page images + N clauses → Gemini Pro → VisionFindings.

One Gemini 2.5 Pro call carries:
  • Instruction prompt (m2_v1.txt)
  • JSON of clauses to address
  • JSON of M1 page manifests (context)
  • All 63 pages as inline PNG images (200 DPI)

On HTTP 429 / ResourceExhausted, the GeminiKeyRotator advances to the next
backup key. On JSON parse failure (truncation from thinking-token exhaust),
retries up to MAX_JSON_RETRY times.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
import google.generativeai as genai
from google.api_core import exceptions as gax_exceptions

from ..config import GeminiKeyRotator
from ..clause_inventory.extract import pydantic_to_gemini_schema
from .schema import VisionFindingsResponse

MODEL_NAME = "gemini-2.5-pro"
EXTRACTOR_VERSION = "m2-v4"
PROMPT_VERSION = "m2-v4"
DEFAULT_RASTER_DPI = 200
MAX_JSON_RETRY = 2
MAX_OUTPUT_TOKENS = 65536

_PROMPT_PATH = Path(__file__).parent / "prompts" / "m2_v4.txt"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def rasterize_all_pages(pdf_path: Path, dpi: int = DEFAULT_RASTER_DPI) -> List[bytes]:
    """Rasterize every page (1-indexed) to PNG bytes at given DPI."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    out: List[bytes] = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out.append(pix.tobytes("png"))
    return out


def filter_normative_clauses(canonical_clauses_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return only is_normative=true clauses, lean shape for the prompt."""
    out: List[Dict[str, Any]] = []
    for c in canonical_clauses_doc.get("clauses", []):
        if not c.get("is_normative"):
            continue
        out.append({
            "clause_id": c.get("clause_id"),
            "clause_text": c.get("clause_text"),
            "category": c.get("category"),
            "page": c.get("page"),
            "is_quantitative": c.get("is_quantitative", False),
        })
    return out


def select_clauses(
    canonical_clauses_doc: Dict[str, Any],
    clause_ids: Optional[Sequence[str]],
) -> List[Dict[str, Any]]:
    """Return clauses matching the given IDs, or all normative clauses if None."""
    normative = filter_normative_clauses(canonical_clauses_doc)
    if not clause_ids:
        return normative
    wanted = set(clause_ids)
    available_ids = {c["clause_id"] for c in normative}
    missing = wanted - available_ids
    if missing:
        # Allow non-normative too if explicitly named (M2 spec says normative-only,
        # but user-named selection is honored for slice testing).
        all_clauses = {c["clause_id"]: c for c in canonical_clauses_doc.get("clauses", [])}
        nonnorm_named = [all_clauses[cid] for cid in missing if cid in all_clauses]
        if len(nonnorm_named) != len(missing):
            unknown = missing - {c["clause_id"] for c in nonnorm_named}
            raise ValueError(
                f"Unknown clause_ids requested: {sorted(unknown)}. "
                f"Available count: {len(all_clauses)}"
            )
        chosen = [c for c in normative if c["clause_id"] in wanted] + [
            {
                "clause_id": c["clause_id"],
                "clause_text": c["clause_text"],
                "category": c["category"],
                "page": c["page"],
                "is_quantitative": c.get("is_quantitative", False),
                "note": "non-normative but explicitly requested",
            }
            for c in nonnorm_named
        ]
        return sorted(chosen, key=lambda x: x["clause_id"])
    return sorted(
        [c for c in normative if c["clause_id"] in wanted],
        key=lambda x: x["clause_id"],
    )


def lean_manifests(page_manifests_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Slim the M1 manifest to fields useful for routing M2's attention."""
    out: List[Dict[str, Any]] = []
    for m in page_manifests_doc.get("manifests", []):
        out.append({
            "page_number": m.get("page_number"),
            "page_type": m.get("page_type"),
            "ta_shetach_refs": m.get("ta_shetach_refs", []),
            "visible_text_labels": m.get("visible_text_labels", []),
            "tables_present": m.get("tables_present", []),
            "page_quality": m.get("page_quality"),
        })
    return out


@dataclass
class CallUsage:
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None


@dataclass
class ExtractionResult:
    response_data: Dict[str, Any]  # raw {plot_reconciliation, findings}
    usage: Optional[CallUsage]
    attempts: int  # total HTTP attempts (key rotations + JSON retries)
    pdf_sha256: str
    canonical_clauses_sha256: str
    page_manifests_sha256: str


def _call_gemini(
    rotator: GeminiKeyRotator,
    prompt: str,
    clauses_json: str,
    manifests_json: str,
    page_pngs: List[bytes],
    schema: Dict[str, Any],
    other_batches_context: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[CallUsage], int]:
    """Send the full extraction request to Gemini Pro.

    Rotates keys on 429; retries on JSON-parse failures (truncated output).
    Returns (parsed_response_dict, usage, total_attempts).

    If `other_batches_context` is given, it is included before the active-batch
    clause list as awareness of clauses being handled by sibling batches. Pro
    should NOT emit findings for those — but knowing they exist helps it scope
    plot_reconciliation work consistently across batches.
    """
    attempts = 0
    json_failures = 0
    parts: List[Any] = [
        prompt,
    ]
    if other_batches_context:
        parts.append(
            "\n\n=== OTHER BATCHES — for context only, DO NOT emit findings ===\n"
            + other_batches_context
        )
    parts.extend([
        "\n\n=== CLAUSES TO ADDRESS (JSON) — emit one or more Finding per item below ===\n"
        + clauses_json,
        "\n\n=== M1 PAGE MANIFESTS (JSON, lean) ===\n" + manifests_json,
        "\n\n=== SUBMISSION PAGES (PNG, 1..63) ===\n",
    ])
    for png in page_pngs:
        parts.append({"mime_type": "image/png", "data": png})

    while True:
        attempts += 1
        genai.configure(api_key=rotator.current())
        model = genai.GenerativeModel(MODEL_NAME)
        try:
            response = model.generate_content(
                parts,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "temperature": 0.0,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                },
            )
        except gax_exceptions.ResourceExhausted as exc:
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All Gemini API keys hit quota (429). Last error: {exc}"
                ) from exc
            print(f"[m2: RETRY #{attempts}] 429 on key, rotating", flush=True)
            continue
        except gax_exceptions.TooManyRequests as exc:  # pragma: no cover
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All Gemini API keys hit quota (429). Last error: {exc}"
                ) from exc
            print(f"[m2: RETRY #{attempts}] 429 on key, rotating", flush=True)
            continue

        usage: Optional[CallUsage] = None
        if getattr(response, "usage_metadata", None) is not None:
            um = response.usage_metadata
            usage = CallUsage(
                prompt_token_count=getattr(um, "prompt_token_count", None),
                candidates_token_count=getattr(um, "candidates_token_count", None),
                total_token_count=getattr(um, "total_token_count", None),
            )

        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except Exception:  # noqa: BLE001
            pass

        payload = response.text
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            json_failures += 1
            if json_failures <= MAX_JSON_RETRY:
                print(
                    f"[m2: RETRY #{json_failures} json] "
                    f"parse failure ({exc.msg} at char {exc.pos}); "
                    f"finish_reason={finish_reason}, usage={usage}",
                    flush=True,
                )
                continue
            raise RuntimeError(
                f"Gemini returned non-JSON output after {json_failures} attempts: {exc}\n"
                f"finish_reason: {finish_reason}\n"
                f"usage: {usage}\n"
                f"---payload prefix---\n{payload[:600]}"
            ) from exc

        # Validate against schema before returning
        try:
            VisionFindingsResponse.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Gemini returned JSON that failed Pydantic validation: {exc}\n"
                f"---payload prefix---\n{payload[:600]}"
            ) from exc

        return data, usage, attempts


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _merge_responses(batch_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge per-batch Pro responses into a single VisionFindingsResponse-shaped dict.

    Findings: concat in clause_id order (stable).
    Plot reconciliation:
      • mappings: dedupe by submission_label. On conflict, keep the highest-confidence
        mapping; tie-break by union of evidence_pages.
      • unreconciled_submission_labels: union (a label flagged by any batch is unreconciled
        unless that same label appears as a mapping in another batch — promotion wins).
      • unreconciled_takanon_plots: intersection (a takanon plot is unreconciled in the
        merged output ONLY IF every batch flagged it; if any batch found evidence we
        treat the plot as reconciled).
      • method: "auto"
    """
    all_findings: List[Dict[str, Any]] = []
    mappings_by_label: Dict[str, Dict[str, Any]] = {}
    all_unreconciled_subs: set = set()
    takanon_unreconciled_per_batch: List[set] = []

    for resp in batch_responses:
        all_findings.extend(resp.get("findings", []) or [])
        pr = resp.get("plot_reconciliation", {}) or {}
        for m in pr.get("mappings", []) or []:
            label = m.get("submission_label")
            if not label:
                continue
            existing = mappings_by_label.get(label)
            if existing is None:
                mappings_by_label[label] = dict(m)  # shallow copy
                continue
            # On conflict: keep higher confidence; merge evidence_pages
            new_rank = _CONFIDENCE_RANK.get(m.get("confidence", "low"), 0)
            old_rank = _CONFIDENCE_RANK.get(existing.get("confidence", "low"), 0)
            if new_rank > old_rank:
                merged = dict(m)
            else:
                merged = dict(existing)
            ev_pages = sorted(
                set((existing.get("evidence_pages") or []) + (m.get("evidence_pages") or []))
            )
            merged["evidence_pages"] = ev_pages
            mappings_by_label[label] = merged
        for u in pr.get("unreconciled_submission_labels", []) or []:
            all_unreconciled_subs.add(u)
        takanon_unreconciled_per_batch.append(
            set(pr.get("unreconciled_takanon_plots", []) or [])
        )

    # Promote: a label that appears in mappings should NOT also be in unreconciled list.
    promoted_labels = set(mappings_by_label.keys())
    final_unreconciled_subs = sorted(all_unreconciled_subs - promoted_labels)

    # Intersection across all batches for unreconciled_takanon_plots
    if takanon_unreconciled_per_batch:
        final_unreconciled_takanon = sorted(set.intersection(*takanon_unreconciled_per_batch))
    else:
        final_unreconciled_takanon = []

    # Sort findings by (clause_id, ta_shetach_takanon) for deterministic output
    def _sort_key(f: Dict[str, Any]) -> Tuple[str, str]:
        cid = f.get("clause_id") or ""
        tak = f.get("ta_shetach_takanon")
        return (cid, tak if tak is not None else "")
    all_findings.sort(key=_sort_key)

    return {
        "plot_reconciliation": {
            "method": "auto",
            "mappings": list(mappings_by_label.values()),
            "unreconciled_submission_labels": final_unreconciled_subs,
            "unreconciled_takanon_plots": final_unreconciled_takanon,
        },
        "findings": all_findings,
    }


def _other_batches_context(
    all_batches: List[List[Dict[str, Any]]], current_idx: int
) -> str:
    """Build the 'context only' preamble listing clause_ids in sibling batches."""
    lines: List[str] = []
    for j, batch in enumerate(all_batches):
        if j == current_idx:
            continue
        ids = [c["clause_id"] for c in batch]
        lines.append(f"Batch {j + 1} (handled separately): {', '.join(ids)}")
    return "\n".join(lines) if lines else ""


def extract(
    pdf_path: Path,
    canonical_clauses_path: Path,
    page_manifests_path: Path,
    clause_ids: Optional[Sequence[str]] = None,
    raster_dpi: int = DEFAULT_RASTER_DPI,
    batch_size: int = 100,
    on_batch_complete: Optional[Callable[[Dict[str, Any], int, int], None]] = None,
) -> ExtractionResult:
    """Run M2 extraction. Single Pro call when batch_size >= len(clauses), else
    splits clauses into batches of `batch_size` and runs one Pro call per batch,
    then merges the results.

    Backward-compat: batch_size=100 (default) yields a single call when there
    are ≤100 clauses, matching pre-m2-v4 behavior.

    Args:
      on_batch_complete: optional callback invoked after each batch's Pro call
        returns and validates. Signature: (partial_merged_response, batch_idx,
        total_batches). Use this for incremental persistence so a mid-run
        crash (network, OOM, quota) doesn't lose previously-completed batches.
    """
    pdf_path = Path(pdf_path).resolve()
    canonical_clauses_path = Path(canonical_clauses_path).resolve()
    page_manifests_path = Path(page_manifests_path).resolve()

    pdf_sha = _sha256_path(pdf_path)
    cc_sha = _sha256_path(canonical_clauses_path)
    pm_sha = _sha256_path(page_manifests_path)

    cc_doc = json.loads(canonical_clauses_path.read_text(encoding="utf-8"))
    pm_doc = json.loads(page_manifests_path.read_text(encoding="utf-8"))

    chosen_clauses = select_clauses(cc_doc, clause_ids)
    if not chosen_clauses:
        raise ValueError("No clauses selected (filter produced empty list)")

    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    # Split into batches
    batches: List[List[Dict[str, Any]]] = [
        chosen_clauses[i : i + batch_size]
        for i in range(0, len(chosen_clauses), batch_size)
    ]

    print(f"[m2] selected {len(chosen_clauses)} clauses for extraction")
    print(f"[m2] batch_size={batch_size} → {len(batches)} batch(es) of size "
          f"{[len(b) for b in batches]}")
    print(f"[m2] rasterizing all pages at {raster_dpi} DPI...")
    page_pngs = rasterize_all_pages(pdf_path, dpi=raster_dpi)
    total_png_bytes = sum(len(p) for p in page_pngs)
    print(f"[m2] rasterized {len(page_pngs)} pages, total {total_png_bytes/1024:.0f} KB")

    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError(
            "No GEMINI_API_KEY env vars set. Export GEMINI_API_KEY (and optionally "
            "GEMINI_API_KEY_BACKUP_1/2/3) before running."
        )

    prompt = load_prompt()
    schema = pydantic_to_gemini_schema(VisionFindingsResponse)
    manifests_json = json.dumps(lean_manifests(pm_doc), ensure_ascii=False, indent=2)

    batch_responses: List[Dict[str, Any]] = []
    total_attempts = 0
    agg_prompt = 0
    agg_candidates = 0
    agg_total = 0

    for idx, batch in enumerate(batches):
        print(f"[m2] === BATCH {idx + 1}/{len(batches)} — {len(batch)} clauses ===")
        clauses_json = json.dumps(batch, ensure_ascii=False, indent=2)
        context_str = _other_batches_context(batches, idx) if len(batches) > 1 else None
        data, usage, attempts = _call_gemini(
            rotator,
            prompt,
            clauses_json,
            manifests_json,
            page_pngs,
            schema,
            other_batches_context=context_str,
        )
        n_findings = len(data.get("findings", []))
        n_mappings = len(data.get("plot_reconciliation", {}).get("mappings", []))
        print(f"[m2] batch {idx + 1} OK — {n_findings} findings, "
              f"{n_mappings} plot mappings, attempts={attempts}, usage={usage}",
              flush=True)
        batch_responses.append(data)
        total_attempts += attempts
        if usage is not None:
            agg_prompt += usage.prompt_token_count or 0
            agg_candidates += usage.candidates_token_count or 0
            agg_total += usage.total_token_count or 0

        # Incremental persistence: hand the partial merged response to caller after
        # every successful batch. A mid-run crash on a later batch then preserves
        # all completed work.
        if on_batch_complete is not None:
            partial_merged = _merge_responses(batch_responses)
            try:
                on_batch_complete(partial_merged, idx + 1, len(batches))
            except Exception as cb_exc:  # noqa: BLE001
                print(
                    f"[m2] WARN: on_batch_complete callback raised: {cb_exc!r} "
                    f"(continuing — partial state may not be persisted for this batch)",
                    flush=True,
                )

    merged = _merge_responses(batch_responses)
    print(f"[m2] MERGED — {len(merged['findings'])} findings, "
          f"{len(merged['plot_reconciliation']['mappings'])} plot mappings, "
          f"total_attempts={total_attempts}, "
          f"agg_usage={{'prompt':{agg_prompt}, 'candidates':{agg_candidates}, 'total':{agg_total}}}")

    agg_usage = CallUsage(
        prompt_token_count=agg_prompt or None,
        candidates_token_count=agg_candidates or None,
        total_token_count=agg_total or None,
    )

    return ExtractionResult(
        response_data=merged,
        usage=agg_usage,
        attempts=total_attempts,
        pdf_sha256=pdf_sha,
        canonical_clauses_sha256=cc_sha,
        page_manifests_sha256=pm_sha,
    )


def build_document(
    project_id: str,
    submission_id: str,
    result: ExtractionResult,
    validation_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the on-disk document around the Gemini response."""
    return {
        "project_id": project_id,
        "submission_id": submission_id,
        "extractor_version": EXTRACTOR_VERSION,
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL_NAME,
        "input_refs": {
            "canonical_clauses_sha256": result.canonical_clauses_sha256,
            "page_manifests_sha256": result.page_manifests_sha256,
            "source_pdf_sha256": result.pdf_sha256,
        },
        "plot_reconciliation": result.response_data.get("plot_reconciliation", {}),
        "findings": result.response_data.get("findings", []),
        "validation_summary": validation_summary,
    }
