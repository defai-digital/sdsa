"""FastAPI routes: upload → process → download → delete."""
from __future__ import annotations

import io
from typing import Any

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
from ..pipeline import PipelineError, ProcessRequest, run_pipeline
from ..report import render_markdown
from ..anonymize.policy import PolicyApplicationError

log = get_logger("sdsa.api")
router = APIRouter(prefix="/api")


class UploadResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    session_ttl_seconds: int
    row_count: int
    column_count: int
    format: str
    encoding: str
    parse_meta: dict
    schema_: list[dict] = Field(..., serialization_alias="schema")
    pii_suggestions: dict[str, dict]
    policy_suggestions: dict[str, dict]


@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile) -> UploadResponse:
    cfg = get_config()
    raw = await file.read()
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
        row_count=df.height,
        column_count=df.width,
        format=result.format,
        encoding=result.encoding,
        parse_meta=result.meta,
        schema_=schema,
        pii_suggestions=pii,
        policy_suggestions=policy_suggestions,
    )


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
    store = get_store()
    session = store.get(session_id)
    if session is None or session.df is None:
        raise HTTPException(404, "session not found or expired")

    detection = session.detection or {"schema": [], "pii": {}}
    # Invalidate any previous successful output before attempting a new run so
    # failed re-processing cannot leave stale downloads attached to the session.
    session.output_bytes = None
    session.output_report = None

    try:
        result = run_pipeline(
            original=session.df,
            request=request,
            session_id=session_id,
            hmac_key=session.hmac_key,
            schema=detection.get("schema", []),
            pii_suggestions=detection.get("pii", {}),
        )
    except (PipelineError, PolicyApplicationError) as e:
        raise HTTPException(400, str(e))

    # Serialize CSV into session bytes buffer.
    buf = io.BytesIO()
    result.df.write_csv(buf)
    session.output_bytes = buf.getvalue()
    session.output_report = result.report

    log.info("process_complete", extra={
        "session_id": session_id,
        "rows_out": result.df.height,
        "cols_out": result.df.width,
    })

    return ProcessResponse(session_id=session_id, report=result.report)


@router.post("/preflight/{session_id}", response_model=PreflightResponse)
async def preflight(session_id: str, request: PreflightRequest) -> PreflightResponse:
    store = get_store()
    session = store.get(session_id)
    if session is None or session.df is None:
        raise HTTPException(404, "session not found or expired")

    try:
        preview = preflight_k_anonymity(
            original=session.df,
            request=request,
            hmac_key=session.hmac_key,
        )
    except PolicyApplicationError as e:
        raise HTTPException(400, str(e))
    return PreflightResponse(session_id=session_id, preflight=preview)


@router.get("/download/{session_id}/data.csv")
async def download_csv(session_id: str):
    store = get_store()
    session = store.get(session_id)
    if session is None or session.output_bytes is None:
        raise HTTPException(404, "no output for session")
    headers = {"Content-Disposition": f'attachment; filename="sdsa-{session_id}.csv"'}
    return Response(content=session.output_bytes, media_type="text/csv", headers=headers)


@router.get("/download/{session_id}/report.json")
async def download_report_json(session_id: str):
    store = get_store()
    session = store.get(session_id)
    if session is None or session.output_report is None:
        raise HTTPException(404, "no report for session")
    return JSONResponse(session.output_report)


@router.get("/download/{session_id}/report.md")
async def download_report_md(session_id: str):
    store = get_store()
    session = store.get(session_id)
    if session is None or session.output_report is None:
        raise HTTPException(404, "no report for session")
    md = render_markdown(session.output_report)
    headers = {"Content-Disposition": f'attachment; filename="sdsa-report-{session_id}.md"'}
    return Response(content=md, media_type="text/markdown", headers=headers)


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    get_store().delete(session_id)
    return {"deleted": session_id}
