"""M3 critic: per-finding Flash call with constrained context.

For each critical M2 finding, build a minimal context (clause text + claimed
value + cited page PNGs only — NOT M2's reasoning) and ask Gemini 2.5 Flash
for an independent verdict.

Mirrors M2's retry + key-rotation pattern. Each call is small (Flash, ~5K
tokens input, ~500 tokens output) so a per-finding strategy is feasible.
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
from .schema import CriticResponse

MODEL_NAME = "gemini-2.5-flash"
CRITIC_VERSION = "m3-v2"
PROMPT_VERSION = "m3-v2"
# DPI bumped from 200 (m3-v1) to 300 in m3-v2. The slice-1 hallucination
# (critic misread "+89.80" as "+91.80" on page 58) was partly attributable
# to elevation-ladder labels being tiny at 200 DPI. 300 DPI gives the critic
# better visual resolution of small numeric labels.
DEFAULT_RASTER_DPI = 300
MAX_JSON_RETRY = 2
# Flash 2.5 thinking tokens are non-deterministic and consume the output budget.
# Slice-1 testing showed a 4096 budget truncates mid-string when the response
# includes multi-page Hebrew citations. 16384 leaves enough headroom for
# thinking + a ~1KB reasoning string.
MAX_OUTPUT_TOKENS = 16384

_PROMPT_PATH = Path(__file__).parent / "prompts" / "m3_v2.txt"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def rasterize_pages(pdf_path: Path, page_numbers: Sequence[int],
                    dpi: int = DEFAULT_RASTER_DPI) -> List[bytes]:
    """Rasterize the given 1-indexed pages to PNG bytes at given DPI."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    out: List[bytes] = []
    with fitz.open(pdf_path) as doc:
        for n in page_numbers:
            if n < 1 or n > doc.page_count:
                raise ValueError(f"page {n} out of range [1, {doc.page_count}]")
            page = doc.load_page(n - 1)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out.append(pix.tobytes("png"))
    return out


def lookup_clause_text(canonical_clauses: List[Dict[str, Any]],
                       clause_id: str) -> str:
    for c in canonical_clauses:
        if c.get("clause_id") == clause_id:
            return c.get("clause_text") or ""
    return ""


@dataclass
class CallUsage:
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None


@dataclass
class CriticCallResult:
    response_data: Dict[str, Any]  # the {verdict, extraction_value, ...} payload
    usage: Optional[CallUsage]
    attempts: int


def _build_user_text(clause_text: str, m2_value: str, m2_indicator: str) -> str:
    """Construct the user-facing context block (NO M2 reasoning, NO bbox hints)."""
    return (
        f"\n\n=== TAKANON CLAUSE (Hebrew, verbatim from תקנון) ===\n{clause_text}\n"
        f"\n=== CLAIMED EXTRACTION VALUE (from the other vision model) ===\n"
        f"{m2_value}\n"
        f"\n=== CLAIMED COMPLIANCE VERDICT (from the other vision model) ===\n"
        f"{m2_indicator}\n"
        f"\n=== CITED SOURCE PAGE IMAGES — verify against these ===\n"
    )


def _call_flash_for_finding(
    rotator: GeminiKeyRotator,
    prompt: str,
    clause_text: str,
    m2_value: str,
    m2_indicator: str,
    page_pngs: List[bytes],
    schema: Dict[str, Any],
) -> CriticCallResult:
    """Send one critic call to Flash. Rotates keys on 429, retries on JSON parse."""
    attempts = 0
    json_failures = 0
    user_text = _build_user_text(clause_text, m2_value, m2_indicator)
    parts: List[Any] = [prompt, user_text]
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
            print(f"[m3: RETRY #{attempts}] 429 on key, rotating", flush=True)
            continue
        except gax_exceptions.TooManyRequests as exc:  # pragma: no cover
            next_key = rotator.rotate()
            if next_key is None:
                raise RuntimeError(
                    f"All Gemini API keys hit quota (429). Last error: {exc}"
                ) from exc
            print(f"[m3: RETRY #{attempts}] 429 on key, rotating", flush=True)
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
                    f"[m3: RETRY #{json_failures} json] "
                    f"parse failure ({exc.msg} at char {exc.pos}); "
                    f"finish_reason={finish_reason}, usage={usage}",
                    flush=True,
                )
                continue
            raise RuntimeError(
                f"Flash returned non-JSON output after {json_failures} attempts: "
                f"{exc}\nfinish_reason: {finish_reason}\nusage: {usage}\n"
                f"---payload prefix---\n{payload[:600]}"
            ) from exc

        try:
            CriticResponse.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Flash returned JSON that failed Pydantic validation: {exc}\n"
                f"---payload prefix---\n{payload[:600]}"
            ) from exc

        return CriticCallResult(response_data=data, usage=usage, attempts=attempts)


def critique_one(
    rotator: GeminiKeyRotator,
    pdf_path: Path,
    canonical_clauses: List[Dict[str, Any]],
    m2_finding: Dict[str, Any],
    raster_dpi: int = DEFAULT_RASTER_DPI,
    schema: Optional[Dict[str, Any]] = None,
) -> CriticCallResult:
    """Run the critic on one M2 finding."""
    if schema is None:
        schema = pydantic_to_gemini_schema(CriticResponse)
    prompt = load_prompt()
    clause_text = lookup_clause_text(canonical_clauses, m2_finding["clause_id"])
    m2_value = str(m2_finding.get("extraction", {}).get("value", "") or "")
    m2_indicator = str(m2_finding.get("compliance_indicator") or "")
    page_pngs = rasterize_pages(pdf_path, m2_finding.get("source_pages") or [],
                                dpi=raster_dpi)
    return _call_flash_for_finding(
        rotator, prompt, clause_text, m2_value, m2_indicator, page_pngs, schema
    )


@dataclass
class ExtractionRunResult:
    critic_findings: List[Dict[str, Any]]
    summary: Dict[str, Any]
    pdf_sha256: str
    vision_findings_sha256: str
    canonical_clauses_sha256: str
    total_attempts: int
    aggregate_usage: Dict[str, int]


def _build_summary(critic_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(critic_findings)
    agree = sum(1 for f in critic_findings if f.get("critic_verdict") == "agree")
    disagree = sum(1 for f in critic_findings if f.get("critic_verdict") == "disagree")
    cannot = sum(1 for f in critic_findings if f.get("critic_verdict") == "cannot_determine")
    critical_disagreements = [
        f.get("clause_id")
        for f in critic_findings
        if f.get("critic_verdict") == "disagree"
        and f.get("disagreement_severity") == "critical"
    ]
    rate = (agree * 100.0 / n) if n else 0.0
    return {
        "critiqued_count": n,
        "agree_count": agree,
        "disagree_count": disagree,
        "cannot_determine_count": cannot,
        "critical_disagreements": critical_disagreements,
        "agreement_rate_pct": round(rate, 2),
    }


def critique_many(
    pdf_path: Path,
    canonical_clauses_path: Path,
    vision_findings_path: Path,
    target_findings: List[Dict[str, Any]],
    raster_dpi: int = DEFAULT_RASTER_DPI,
    on_finding_complete: Optional[Callable[[List[Dict[str, Any]], int, int], None]] = None,
) -> ExtractionRunResult:
    """Critique a sequence of M2 findings, one Flash call each."""
    pdf_path = Path(pdf_path).resolve()
    canonical_clauses_path = Path(canonical_clauses_path).resolve()
    vision_findings_path = Path(vision_findings_path).resolve()

    pdf_sha = _sha256_path(pdf_path)
    vf_sha = _sha256_path(vision_findings_path)
    cc_sha = _sha256_path(canonical_clauses_path)

    cc_doc = json.loads(canonical_clauses_path.read_text(encoding="utf-8"))
    canonical_clauses = cc_doc.get("clauses", [])

    rotator = GeminiKeyRotator()
    if not rotator.has_keys:
        raise RuntimeError(
            "No GEMINI_API_KEY env vars set. Export GEMINI_API_KEY (and optionally "
            "GEMINI_API_KEY_BACKUP_1/2/3) before running."
        )

    schema = pydantic_to_gemini_schema(CriticResponse)
    critic_findings: List[Dict[str, Any]] = []
    total_attempts = 0
    agg_prompt = 0
    agg_candidates = 0
    agg_total = 0

    print(f"[m3] critiquing {len(target_findings)} M2 findings via "
          f"{MODEL_NAME}...", flush=True)

    for idx, m2f in enumerate(target_findings):
        cid = m2f.get("clause_id")
        plot = m2f.get("ta_shetach_takanon")
        n_pages = len(m2f.get("source_pages") or [])
        print(f"[m3] === FINDING {idx + 1}/{len(target_findings)} — "
              f"clause {cid}, plot={plot}, {n_pages} cited pages ===", flush=True)

        result = critique_one(rotator, pdf_path, canonical_clauses, m2f,
                              raster_dpi=raster_dpi, schema=schema)
        total_attempts += result.attempts
        if result.usage is not None:
            agg_prompt += result.usage.prompt_token_count or 0
            agg_candidates += result.usage.candidates_token_count or 0
            agg_total += result.usage.total_token_count or 0

        resp = result.response_data
        critic_record = {
            "clause_id": cid,
            "m2_extraction_value": str(m2f.get("extraction", {}).get("value", "") or ""),
            "m2_compliance_indicator": m2f.get("compliance_indicator"),
            "m2_source_pages": list(m2f.get("source_pages") or []),
            "critic_verdict": resp.get("verdict"),
            "critic_extraction_value": resp.get("extraction_value"),
            "critic_compliance_indicator": resp.get("compliance_indicator"),
            "critic_reasoning": resp.get("reasoning") or "",
            "disagreement_severity": resp.get("disagreement_severity"),
        }
        critic_findings.append(critic_record)

        verdict_str = critic_record["critic_verdict"]
        sev = f"/{critic_record['disagreement_severity']}" if critic_record.get("disagreement_severity") else ""
        print(f"[m3] finding {idx + 1} OK — verdict={verdict_str}{sev}, "
              f"attempts={result.attempts}, usage={result.usage}", flush=True)

        if on_finding_complete is not None:
            try:
                on_finding_complete(list(critic_findings), idx + 1, len(target_findings))
            except Exception as cb_exc:  # noqa: BLE001
                print(f"[m3] WARN: on_finding_complete callback raised: {cb_exc!r} "
                      f"(continuing — incremental save may have failed for this finding)",
                      flush=True)

    summary = _build_summary(critic_findings)
    print(f"[m3] DONE — {summary['agree_count']} agree / "
          f"{summary['disagree_count']} disagree / "
          f"{summary['cannot_determine_count']} cannot_determine "
          f"({summary['agreement_rate_pct']}% agreement)", flush=True)

    return ExtractionRunResult(
        critic_findings=critic_findings,
        summary=summary,
        pdf_sha256=pdf_sha,
        vision_findings_sha256=vf_sha,
        canonical_clauses_sha256=cc_sha,
        total_attempts=total_attempts,
        aggregate_usage={
            "prompt_token_count": agg_prompt,
            "candidates_token_count": agg_candidates,
            "total_token_count": agg_total,
        },
    )


def build_document(
    project_id: str,
    submission_id: str,
    result: ExtractionRunResult,
) -> Dict[str, Any]:
    """Assemble the on-disk document."""
    return {
        "project_id": project_id,
        "submission_id": submission_id,
        "critic_version": CRITIC_VERSION,
        "critic_model": MODEL_NAME,
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_refs": {
            "vision_findings_sha256": result.vision_findings_sha256,
            "source_pdf_sha256": result.pdf_sha256,
            "canonical_clauses_sha256": result.canonical_clauses_sha256,
        },
        "critic_findings": result.critic_findings,
        "summary": result.summary,
    }
