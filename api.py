import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.hospital_agents import run_hospital_optimization
from tools.hospital_tools import analyze_capacity_and_staffing, load_hospital_snapshot

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

app = FastAPI(
    title="Hospital Resource & Patient Flow Optimizer (AutoGen + FastAPI)",
    version="1.0.0",
)

static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class OptimizeRequest(BaseModel):
    extra_admissions_next_4h: int = Field(default=12, ge=0, le=200)
    expedited_discharges_next_4h: int = Field(default=6, ge=0, le=200)
    max_messages: int = Field(default=10, ge=4, le=20)


@app.get("/")
def serve_ui() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health_check() -> dict[str, object]:
    return {
        "status": "healthy",
        "groq_key_configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    }


@app.get("/api/snapshot")
def get_snapshot() -> dict[str, object]:
    snapshot = load_hospital_snapshot(str(BASE_DIR / "data" / "hospital_snapshot.json"))
    if "error" in snapshot:
        raise HTTPException(status_code=404, detail=snapshot["error"])
    summary = analyze_capacity_and_staffing(snapshot)
    return {
        "snapshot": snapshot,
        "summary": summary,
    }


@app.post("/api/optimize")
async def optimize_flow(payload: OptimizeRequest) -> dict[str, object]:
    if not os.getenv("GROQ_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="GROQ_API_KEY is not set in .env")
    try:
        return await run_hospital_optimization(
            extra_admissions_next_4h=payload.extra_admissions_next_4h,
            expedited_discharges_next_4h=payload.expedited_discharges_next_4h,
            snapshot_path=str(BASE_DIR / "data" / "hospital_snapshot.json"),
            max_messages=payload.max_messages,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc