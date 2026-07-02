"""
Relay AI Ad Pipeline — FastAPI Backend.

Provides REST endpoints for the frontend to:
1. Submit a transcript and run the full pipeline.
2. Download the pipeline report as Markdown.
3. Access per-stage JSON outputs.

Usage:
    uvicorn api:app --reload --port 8000
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse, Response
# pyrefly: ignore [missing-import]
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.orchestrator import run_pipeline

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Relay AI Ad Pipeline",
    description="AI-powered ad analysis and creative generation pipeline.",
    version="1.0.0",
)

# CORS — allow frontend on same origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ---------------------------------------------------------------------------
# In-memory store for the last pipeline result
# ---------------------------------------------------------------------------

_last_result: dict | None = None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PipelineRequest(BaseModel):
    transcript: str


class PipelineResponse(BaseModel):
    status: str
    timestamp: str
    report: str
    stage_1_output: dict | None = None
    stage_2_output: dict | None = None
    stage_3_output: dict | None = None
    stage_4_output: dict | None = None
    error: dict | None = None
    token_usage: dict | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the frontend HTML page."""
    html_path = static_dir / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found. Create static/index.html.")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/pipeline", response_model=PipelineResponse)
async def run_pipeline_endpoint(request: PipelineRequest):
    """
    Run the full Relay AI Ad Pipeline on the provided transcript.
    Returns the pipeline result with report and per-stage JSON outputs.
    """
    global _last_result

    if not request.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty.")

    logger.info("Pipeline request received (%d chars).", len(request.transcript))

    try:
        # Run in a separate thread to avoid asyncio event loop conflict
        # with gremlinpython's aiohttp transport
        result = await asyncio.to_thread(run_pipeline, request.transcript)
        _last_result = result
        logger.info("Pipeline completed with status: %s", result["status"])
        return PipelineResponse(**result)

    except Exception as e:
        logger.error("Pipeline failed with exception: %s", e)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.get("/api/download/report")
async def download_report():
    """Download the last pipeline report as a Markdown file."""
    if not _last_result:
        raise HTTPException(status_code=404, detail="No pipeline result available. Run the pipeline first.")

    report = _last_result.get("report", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"ad_pipeline_report_{timestamp}.md"

    return Response(
        content=report,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/download/json")
async def download_json():
    """Download the full pipeline result as a JSON file."""
    if not _last_result:
        raise HTTPException(status_code=404, detail="No pipeline result available. Run the pipeline first.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"ad_pipeline_result_{timestamp}.json"

    return Response(
        content=json.dumps(_last_result, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/stage/{stage_num}")
async def get_stage_output(stage_num: int):
    """Get the JSON output for a specific stage (1-4)."""
    if not _last_result:
        raise HTTPException(status_code=404, detail="No pipeline result available.")

    if stage_num not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="Stage must be 1, 2, 3, or 4.")

    key = f"stage_{stage_num}_output"
    output = _last_result.get(key)

    if output is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stage {stage_num} output not available (pipeline may have failed before this stage).",
        )

    return output
