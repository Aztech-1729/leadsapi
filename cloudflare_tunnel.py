import asyncio
import re
import subprocess
import datetime
from db import get_db

def kill_existing():
    try:
        subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
        import time; time.sleep(1)
    except Exception:
        pass

async def start_tunnel(port: int):
    db = get_db()
    await db.config.update_one(
        {"name": "leads_tunnel"},
        {"$set": {"url": "⏳ Restarting...", "updated_at": datetime.datetime.utcnow().isoformat()}},
        upsert=True
    )
    kill_existing()
    process = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--url", f"http://localhost:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    print("⏳ Waiting for Cloudflare tunnel...")
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode()
        match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", text)
        if match:
            url = match.group(0)
            await db.config.update_one(
                {"name": "leads_tunnel"},
                {"$set": {"url": url, "updated_at": datetime.datetime.utcnow().isoformat()}},
                upsert=True
            )
            print(f"🔥 Tunnel live: {url}")
            break
    await process.wait()
