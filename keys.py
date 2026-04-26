"""
Apify key management — all reads/writes go to MongoDB.
No keys are ever stored in Python memory.
"""
from apify_client import ApifyClient
from db import get_db


# ── helpers ──────────────────────────────────────────────────────────────────

async def _get_doc():
    db = get_db()
    doc = await db.config.find_one({"type": "apify_keys"})
    if not doc:
        # Bootstrap empty document so the bot can add keys later
        await db.config.insert_one({
            "type": "apify_keys",
            "keys": [],
            "current_index": 0
        })
        return {"keys": [], "current_index": 0}
    return doc


# ── public API ────────────────────────────────────────────────────────────────

async def get_client() -> ApifyClient:
    """Return an ApifyClient using the currently active key."""
    doc = await _get_doc()
    keys = doc.get("keys", [])
    if not keys:
        raise RuntimeError("No Apify keys configured. Add one via the bot.")
    idx = doc.get("current_index", 0) % len(keys)
    return ApifyClient(keys[idx])


async def rotate_key():
    """Atomically advance the current_index to the next key."""
    db = get_db()
    doc = await _get_doc()
    keys = doc.get("keys", [])
    if not keys:
        return
    new_idx = (doc.get("current_index", 0) + 1) % len(keys)
    await db.config.update_one(
        {"type": "apify_keys"},
        {"$set": {"current_index": new_idx}}
    )


async def add_key(key: str) -> int:
    """Append a key. Returns new total count."""
    db = get_db()
    doc = await _get_doc()
    keys = doc.get("keys", [])
    if key in keys:
        return len(keys)                          # already present — idempotent
    await db.config.update_one(
        {"type": "apify_keys"},
        {"$push": {"keys": key}},
        upsert=True
    )
    return len(keys) + 1


async def remove_key(key: str) -> int:
    """Remove a key. Returns remaining count."""
    db = get_db()
    doc = await _get_doc()
    keys = doc.get("keys", [])
    await db.config.update_one(
        {"type": "apify_keys"},
        {"$pull": {"keys": key}}
    )
    # Reset index if it would now be out of range
    remaining = [k for k in keys if k != key]
    if remaining:
        new_idx = doc.get("current_index", 0) % len(remaining)
        await db.config.update_one(
            {"type": "apify_keys"},
            {"$set": {"current_index": new_idx}}
        )
    return len(remaining)


async def list_keys() -> list[dict]:
    """Return all keys with masked display and active flag."""
    doc = await _get_doc()
    keys = doc.get("keys", [])
    idx = doc.get("current_index", 0) % len(keys) if keys else 0
    return [
        {
            "index": i,
            "masked": k[:12] + "..." + k[-6:],
            "active": i == idx,
            "full": k
        }
        for i, k in enumerate(keys)
    ]
