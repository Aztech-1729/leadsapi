"""
Global Lead Generation API — Optimized
Features:
  - Parallel scraping (5x–10x faster)
  - MongoDB cache (24hr TTL)
  - Plan-based limits (free/basic/pro/unlimited)
  - Same auth architecture as Instagram API
"""
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import datetime
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

class PrettyJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, indent=2, ensure_ascii=False).encode("utf-8")

from db import get_db
import keys as key_manager
from leads_service import run_leads_pipeline, PLAN_LIMITS

app = FastAPI(
    title="LeadsAPI",
    version="2.0.0",
    description="Global Lead Generation SaaS — Parallel + Cached",
    default_response_class=PrettyJSONResponse
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_user(api_key: str):
    db = get_db()
    return await db.users.find_one({"api_key": api_key})


async def _check_user(user: dict) -> tuple[bool, str]:
    today = datetime.date.today().isoformat()
    if user.get("paused"):
        return False, "Your account is paused. Contact admin."
    daily_used = user.get("daily", {}).get(today, 0)
    daily_limit = user.get("daily_limit", 100)
    if daily_used >= daily_limit:
        return False, f"Daily limit of {daily_limit} requests reached. Resets at midnight UTC."
    return True, "OK"


async def _update_usage(api_key: str):
    db = get_db()
    today = datetime.date.today().isoformat()
    await db.users.update_one(
        {"api_key": api_key},
        {"$inc": {
            f"daily.{today}": 1,
            "monthly_count": 1,
            "total_requests": 1
        }}
    )


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {
        "status":  "online",
        "version": "2.0.0",
        "service": "LeadsAPI — Global Lead Generation",
        "plans":   PLAN_LIMITS
    }


@app.get("/leads")
async def leads_endpoint(
    query: str,
    x_api_key: str = Header(...),
    grid_size: int = 2,
):
    """
    Generate enriched business leads for any query.

    **query**: e.g. `gyms in hyderabad`, `restaurants in dubai`
    **grid_size**: coverage radius — 1 (fast), 2 (default), 3 (thorough)

    Returns deduplicated leads with email, phone, confidence score.
    Results are cached for 24 hours.
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    user = await _get_user(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    allowed, msg = await _check_user(user)
    if not allowed:
        raise HTTPException(status_code=403, detail=msg)

    # ── Validate ──────────────────────────────────────────────────────────────
    query = query.strip()
    if not query or len(query) < 5:
        raise HTTPException(status_code=400, detail="Query too short. Example: 'gyms in hyderabad'")
    if grid_size not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="grid_size must be 1, 2, or 3")

    # ── Get user plan → controls max websites ──────────────────────────────────
    user_plan = user.get("plan", "basic")

    # ── Get Apify client ──────────────────────────────────────────────────────
    try:
        apify_client = await key_manager.get_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # ── Run pipeline ──────────────────────────────────────────────────────────
    try:
        leads, error = await run_leads_pipeline(
            query=query,
            apify_client=apify_client,
            rotate_key_fn=key_manager.rotate_key,
            grid_size=grid_size,
            user_plan=user_plan,
        )
    except Exception as exc:
        await key_manager.rotate_key()
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {str(exc)}")

    if error:
        raise HTTPException(status_code=422, detail=error)

    # ── Update usage ──────────────────────────────────────────────────────────
    await _update_usage(x_api_key)

    return {
        "query":       query,
        "plan":        user_plan,
        "total_leads": len(leads),
        "leads":       leads
    }


@app.get("/me")
async def me(x_api_key: str = Header(...)):
    """Check your usage stats."""
    user = await _get_user(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    today = datetime.date.today().isoformat()
    return {
        "api_key":        x_api_key[:8] + "...",
        "plan":           user.get("plan", "basic"),
        "max_websites":   PLAN_LIMITS.get(user.get("plan", "basic"), 25),
        "daily_used":     user.get("daily", {}).get(today, 0),
        "daily_limit":    user.get("daily_limit", 100),
        "monthly_count":  user.get("monthly_count", 0),
        "total_requests": user.get("total_requests", 0),
        "paused":         user.get("paused", False)
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )
