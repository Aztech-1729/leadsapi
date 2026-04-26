"""
Leads Service — Optimized
Full pipeline with:
  - Parallel Maps scraping (5x–10x faster)
  - Parallel contact scraping
  - MongoDB cache (saves cost + time)
  - Plan-based MAX_WEBSITES control
  - Improved email filtering
"""
import asyncio
import logging
import datetime
from typing import Optional

from apify_client import ApifyClient

from db import get_db
from utils.location import extract_location, geocode, generate_grid
from utils.cleaner import merge_lead, deduplicate, is_valid_email, normalize_url

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────
MAPS_ACTOR    = "xmiso_scrapers/google-maps-scraper"
CONTACT_ACTOR = "happyfhantum/verified-website-contact-scraper"
MAPS_RESULTS  = 20
GRID_SIZE     = 2
GRID_STEP     = 0.05
CACHE_TTL_HRS = 24     # cache results for 24 hours

# Plan-based limits
PLAN_LIMITS = {
    "free":       10,
    "basic":      25,
    "pro":        50,
    "unlimited": 100,
}
DEFAULT_MAX_WEBSITES = 25


# ── cache ─────────────────────────────────────────────────────────────────────

async def _get_cache(query: str) -> Optional[list]:
    db = get_db()
    key = query.strip().lower()
    doc = await db.leads_cache.find_one({"query": key})
    if not doc:
        return None
    # Check expiry
    created = doc.get("created_at")
    if not created:
        return None
    age = (datetime.datetime.utcnow() - created).total_seconds() / 3600
    if age > CACHE_TTL_HRS:
        await db.leads_cache.delete_one({"query": key})
        return None
    logger.info(f"💾 Cache hit for: {query}")
    return doc["data"]


async def _set_cache(query: str, data: list):
    db = get_db()
    key = query.strip().lower()
    await db.leads_cache.update_one(
        {"query": key},
        {"$set": {
            "query":      key,
            "data":       data,
            "created_at": datetime.datetime.utcnow(),
            "count":      len(data)
        }},
        upsert=True
    )
    logger.info(f"💾 Cached {len(data)} leads for: {query}")


# ── Google Maps scraper ───────────────────────────────────────────────────────

def _run_maps_scraper(client: ApifyClient, query: str, lat: float, lon: float) -> list[dict]:
    try:
        run = client.actor(MAPS_ACTOR).call(
            run_input={
                "searchQuery": query,
                "latitude":    lat,
                "longitude":   lon,
                "maxResults":  MAPS_RESULTS,
            }
        )
        return list(client.dataset(run["defaultDatasetId"]).iterate_items())
    except Exception as e:
        logger.warning(f"Maps failed at ({lat},{lon}): {e}")
        return []


# ── Contact scraper ───────────────────────────────────────────────────────────

def _run_contact_scraper(client: ApifyClient, website: str) -> dict:
    try:
        run = client.actor(CONTACT_ACTOR).call(
            run_input={"startUrls": [{"url": website}]}
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return items[0] if items else {}
    except Exception as e:
        logger.warning(f"Contact failed for {website}: {e}")
        return {}


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_leads_pipeline(
    query: str,
    apify_client: ApifyClient,
    rotate_key_fn,
    grid_size: int = GRID_SIZE,
    user_plan: str = "basic",
) -> tuple[list[dict], Optional[str]]:
    """
    Full optimized leads pipeline.
    Returns (leads_list, error_message_or_None)
    """
    loop = asyncio.get_event_loop()

    # ── Cache check ───────────────────────────────────────────────────────────
    cached = await _get_cache(query)
    if cached is not None:
        return cached, None

    # ── Step 1: Extract location ──────────────────────────────────────────────
    location = extract_location(query)
    if not location:
        return [], "Could not extract location. Use format: 'gyms in hyderabad'"

    # ── Step 2: Geocode ───────────────────────────────────────────────────────
    geo = await geocode(location)
    if not geo:
        return [], f"Could not find coordinates for: '{location}'"

    lat, lon = geo["lat"], geo["lon"]
    logger.info(f"📍 {geo['display_name']} ({lat}, {lon})")

    # ── Step 3: Generate grid ─────────────────────────────────────────────────
    grid = generate_grid(lat, lon, step=GRID_STEP, size=grid_size)
    logger.info(f"🗺️  Grid: {len(grid)} points")

    # ── Step 4: PARALLEL Maps scraping ───────────────────────────────────────
    logger.info("🔍 Running Maps scrapers in parallel...")
    maps_tasks = [
        loop.run_in_executor(
            None,
            lambda p=point: _run_maps_scraper(apify_client, query, p["lat"], p["lon"])
        )
        for point in grid
    ]

    try:
        maps_results = await asyncio.gather(*maps_tasks, return_exceptions=True)
    except Exception as e:
        await rotate_key_fn()
        return [], f"Maps scraping failed: {str(e)}"

    all_businesses: list[dict] = []
    for result in maps_results:
        if isinstance(result, Exception):
            logger.warning(f"Grid point failed: {result}")
            continue
        all_businesses.extend(result)

    logger.info(f"✅ Raw businesses: {len(all_businesses)}")

    # ── Step 5: Filter + deduplicate websites ─────────────────────────────────
    max_websites = PLAN_LIMITS.get(user_plan, DEFAULT_MAX_WEBSITES)
    website_to_biz: dict[str, dict] = {}
    for biz in all_businesses:
        website = (biz.get("website") or "").strip()
        if not website:
            continue
        domain = normalize_url(website)
        if not domain:
            continue
        if domain not in website_to_biz:
            website_to_biz[domain] = biz

    unique_bizs = list(website_to_biz.values())[:max_websites]
    logger.info(f"🌐 Unique websites to enrich: {len(unique_bizs)} (plan: {user_plan}, limit: {max_websites})")

    if not unique_bizs:
        return [], "No businesses with websites found for this query"

    # ── Step 6: PARALLEL Contact scraping ─────────────────────────────────────
    logger.info("📧 Running contact scrapers in parallel...")
    contact_tasks = [
        loop.run_in_executor(
            None,
            lambda w=biz.get("website", ""): _run_contact_scraper(apify_client, w)
        )
        for biz in unique_bizs
    ]

    try:
        contact_results = await asyncio.gather(*contact_tasks, return_exceptions=True)
    except Exception as e:
        await rotate_key_fn()
        logger.warning(f"Contact scraping error: {e}")
        contact_results = [{}] * len(unique_bizs)

    # ── Step 7: Merge + filter ────────────────────────────────────────────────
    raw_leads: list[dict] = []
    for biz, contact in zip(unique_bizs, contact_results):
        if isinstance(contact, Exception):
            logger.warning(f"Contact failed for {biz.get('website')}: {contact}")
            contact = {}

        lead = merge_lead(biz, contact)

        if is_valid_email(lead.get("email", "")):
            raw_leads.append(lead)
            logger.info(f"  ✅ {lead['name']} → {lead['email']}")
        else:
            logger.info(f"  ❌ {biz.get('title','?')} → no valid email")

    # ── Step 8: Deduplicate + sort ────────────────────────────────────────────
    final_leads = deduplicate(raw_leads)
    logger.info(f"🎯 Final leads: {len(final_leads)}")

    # ── Cache results ─────────────────────────────────────────────────────────
    if final_leads:
        await _set_cache(query, final_leads)

    return final_leads, None
