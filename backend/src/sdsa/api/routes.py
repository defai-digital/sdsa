"""FastAPI routes: upload → process → download → delete."""
from __future__ import annotations

import io
import threading
from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..core.session import get_store
from ..detect.pii import detect_dataframe
from ..detect.schema import infer_schema
from ..ingest import ParseError, parse_upload
from ..policy_config import PolicyConfigError, build_policy_suggestions
from ..preflight import PreflightRequest, preflight_k_anonymity
from ..pipeline import PipelineError, ProcessRequest, _derive_deterministic_key, run_pipeline
from ..report import render_markdown
from ..anonymize.policy import PolicyApplicationError, apply_policy
from ..dp.laplace import LaplaceParams, apply_laplace

# A small fixed cap so preview can never leak more than a handful of rows back
# to the client and is always cheap to render. Five rows is enough to make
# transformations legible without scaring users with a wall of data.
PREVIEW_ROW_LIMIT = 5

log = get_logger("sdsa.api")
router = APIRouter(prefix="/api")

_processing_sessions: set[str] = set()
_processing_lock = threading.Lock()


class UploadResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    session_ttl_seconds: int
    session_expires_at: float
    default_k: int
    row_count: int
    column_count: int
    format: str
    encoding: str
    parse_meta: dict
    schema_: list[dict] = Field(..., serialization_alias="schema")
    pii_suggestions: dict[str, dict]
    policy_suggestions: dict[str, dict]
    sample_columns: list[str]
    sample_rows: list[list[str | None]]


@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile) -> UploadResponse:
    cfg = get_config()
    raw = await file.read(cfg.max_upload_bytes + 1)
    if len(raw) > cfg.max_upload_bytes:
        raise HTTPException(413, "file exceeds max upload size")

    try:
        result = parse_upload(file.filename or "", raw)
    except ParseError as e:
        raise HTTPException(400, str(e))

    df = result.df
    sample = df.head(cfg.sample_rows_for_detection)
    schema = infer_schema(df)
    pii = {k: asdict_pii(v) for k, v in detect_dataframe(sample).items()}
    preview_sample = _serialize_sample(df.head(PREVIEW_ROW_LIMIT))
    try:
        policy_suggestions = build_policy_suggestions(schema, pii)
    except PolicyConfigError as e:
        raise HTTPException(400, str(e))

    store = get_store()
    session = store.create()
    session.df = df
    session.detection = {
        "schema": schema,
        "pii": pii,
        "policy_suggestions": policy_suggestions,
    }

    log.info("upload_complete", extra={
        "session_id": session.session_id,
        "rows": df.height,
        "cols": df.width,
        "format": result.format,
        "encoding": result.encoding,
    })

    return UploadResponse(
        session_id=session.session_id,
        session_ttl_seconds=cfg.session_ttl_seconds,
        session_expires_at=session.created_at + cfg.session_ttl_seconds,
        default_k=cfg.default_k,
        row_count=df.height,
        column_count=df.width,
        format=result.format,
        encoding=result.encoding,
        parse_meta=result.meta,
        schema_=schema,
        pii_suggestions=pii,
        policy_suggestions=policy_suggestions,
        sample_columns=df.columns,
        sample_rows=preview_sample,
    )


def _stringify_cell(v: Any) -> str | None:
    if v is None:
        return None
    # Floats with long tails clutter the preview; trim to 6 sig digits.
    if isinstance(v, float):
        return f"{v:.6g}"
    s = str(v)
    if len(s) > 80:
        return s[:77] + "…"
    return s


def _serialize_sample(df: pl.DataFrame) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    cols = df.columns
    for row in df.iter_rows():
        rows.append([_stringify_cell(row[i]) for i in range(len(cols))])
    return rows


def asdict_pii(s) -> dict[str, Any]:
    return {"kind": s.kind, "confidence": round(s.confidence, 3), "reason": s.reason}


class ProcessResponse(BaseModel):
    session_id: str
    report: dict
    ready_for_download: bool = True


class PreflightResponse(BaseModel):
    session_id: str
    preflight: dict


@router.post("/process/{session_id}", response_model=ProcessResponse)
async def process(session_id: str, request: ProcessRequest) -> ProcessResponse:
    with _processing_lock:
        if session_id in _processing_sessions:
            raise HTTPException(409, "processing already in progress for this session")
        _processing_sessions.add(session_id)
    try:
        store = get_store()
        snapshot = store.checkout(session_id)
        if snapshot is None or snapshot.df is None or snapshot.hmac_key is None:
            raise HTTPException(404, "session not found or expired")

        detection = snapshot.detection or {"schema": [], "pii": {}}
        # Best-effort clear of previous output. If the session was reaped
        # between checkout and here the snapshot is still valid — proceed
        # with the data we already have rather than failing spuriously.
        store.clear_output(session_id)

        try:
            result = run_pipeline(
                original=snapshot.df,
                request=request,
                session_id=session_id,
                hmac_key=snapshot.hmac_key,
                schema=detection.get("schema", []),
                pii_suggestions=detection.get("pii", {}),
            )
        except (PipelineError, PolicyApplicationError) as e:
            raise HTTPException(400, str(e))

        # Serialize CSV into session bytes buffer.
        buf = io.BytesIO()
        result.df.write_csv(buf)
        if not store.store_output(session_id, buf.getvalue(), result.report):
            raise HTTPException(404, "session expired — please re-upload and reprocess")

        log.info("process_complete", extra={
            "session_id": session_id,
            "rows_out": result.df.height,
            "cols_out": result.df.width,
        })

        return ProcessResponse(session_id=session_id, report=result.report)
    finally:
        with _processing_lock:
            _processing_sessions.discard(session_id)


class PreviewResponse(BaseModel):
    session_id: str
    columns: list[str]
    original: list[list[str | None]]
    sanitized: list[list[str | None]]
    dropped_columns: list[str]


@router.post("/preview/{session_id}", response_model=PreviewResponse)
async def preview(session_id: str, request: ProcessRequest) -> PreviewResponse:
    """Return a small before/after sample under the given policies.

    Skips k-anonymity (it would suppress all rows of a tiny sample). DP noise
    is applied so the user sees realistic post-noise values.
    """
    store = get_store()
    snapshot = store.checkout(session_id)
    if snapshot is None or snapshot.df is None or snapshot.hmac_key is None:
        raise HTTPException(404, "session not found or expired")

    head = snapshot.df.head(PREVIEW_ROW_LIMIT)
    cols_in = head.columns
    cfg = get_config()

    # Apply same deterministic key derivation as pipeline/preflight.
    hmac_key = snapshot.hmac_key
    if request.deterministic_key_name:
        if cfg.deployment_salt_is_ephemeral:
            raise HTTPException(400, "Deterministic mode requires SDSA_DEPLOYMENT_SALT to be set.")
        hmac_key = _derive_deterministic_key(request.deterministic_key_name, cfg.deployment_salt)

    df = head.clone()
    dp_columns = {p.column for p in request.policies if p.action == "dp_laplace"}
    if request.deterministic_key_name and dp_columns:
        raise HTTPException(
            400,
            "Deterministic mode cannot be combined with DP columns (ADR-0008)."
        )

    try:
        for p in request.policies:
            df = apply_policy(df, p, hmac_key)

        for col in dp_columns:
            if col not in df.columns:
                continue
            params = request.dp_params.get(col) or {}
            if "epsilon" not in params or "lower" not in params or "upper" not in params:
                # Preview is best-effort: skip incomplete DP configs rather than
                # error out — the Process step will surface the real error.
                continue
            try:
                eps = float(params["epsilon"])
            except (TypeError, ValueError):
                continue
            if not (cfg.epsilon_min <= eps <= cfg.epsilon_max):
                raise HTTPException(
                    400,
                    f"epsilon for '{col}' ({eps:.6g}) outside allowed range "
                    f"[{cfg.epsilon_min}, {cfg.epsilon_max}]",
                )
            try:
                lp = LaplaceParams(
                    epsilon=eps,
                    lower=float(params["lower"]),
                    upper=float(params["upper"]),
                )
            except (TypeError, ValueError):
                continue
            if not df[col].dtype.is_numeric():
                continue
            try:
                df = df.with_columns(apply_laplace(df[col], lp).alias(col))
            except ValueError:
                continue
    except PolicyApplicationError as e:
        raise HTTPException(400, str(e))

    dropped = [c for c in cols_in if c not in df.columns]
    sanitized: list[list[str | None]] = []
    for i in range(head.height):
        row: list[str | None] = []
        for c in cols_in:
            if c in df.columns:
                row.append(_stringify_cell(df[c][i]))
            else:
                row.append(None)  # dropped — frontend renders a marker
        sanitized.append(row)

    return PreviewResponse(
        session_id=session_id,
        columns=cols_in,
        original=_serialize_sample(head),
        sanitized=sanitized,
        dropped_columns=dropped,
    )


@router.post("/preflight/{session_id}", response_model=PreflightResponse)
async def preflight(session_id: str, request: PreflightRequest) -> PreflightResponse:
    store = get_store()
    snapshot = store.checkout(session_id)
    if snapshot is None or snapshot.df is None or snapshot.hmac_key is None:
        raise HTTPException(404, "session not found or expired")

    try:
        preview = preflight_k_anonymity(
            original=snapshot.df,
            request=request,
            hmac_key=snapshot.hmac_key,
        )
    except PolicyApplicationError as e:
        raise HTTPException(400, str(e))
    return PreflightResponse(session_id=session_id, preflight=preview)


@router.get("/download/{session_id}/data.csv")
async def download_csv(session_id: str):
    store = get_store()
    snapshot = store.checkout(session_id)
    if snapshot is None:
        raise HTTPException(404, "session expired — please re-upload and reprocess")
    if snapshot.output_bytes is None:
        raise HTTPException(404, "no output for session")
    headers = {"Content-Disposition": 'attachment; filename="sdsa-export.csv"'}
    return Response(content=snapshot.output_bytes, media_type="text/csv", headers=headers)


@router.get("/download/{session_id}/report.json")
async def download_report_json(session_id: str):
    store = get_store()
    snapshot = store.checkout(session_id)
    if snapshot is None:
        raise HTTPException(404, "session expired — please re-upload and reprocess")
    if snapshot.output_report is None:
        raise HTTPException(404, "no report for session")
    return JSONResponse(snapshot.output_report)


@router.get("/download/{session_id}/report.md")
async def download_report_md(session_id: str):
    store = get_store()
    snapshot = store.checkout(session_id)
    if snapshot is None:
        raise HTTPException(404, "session expired — please re-upload and reprocess")
    if snapshot.output_report is None:
        raise HTTPException(404, "no report for session")
    md = render_markdown(snapshot.output_report)
    headers = {"Content-Disposition": 'attachment; filename="sdsa-report.md"'}
    return Response(content=md, media_type="text/markdown", headers=headers)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if not get_store().delete(session_id):
        raise HTTPException(404, "session not found or already deleted")
    return {"deleted": session_id}
