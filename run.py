"""
Launch all LeadsAPI services:
  1. Kill old processes
  2. Cloudflare tunnel
  3. Uvicorn (FastAPI) on port 5001
  4. Telegram admin bot
"""
import asyncio
import subprocess
import sys
import signal
import config
import cloudflare_tunnel as cloudflare


def kill_old():
    subprocess.run(["pkill", "-f", "uvicorn"],      capture_output=True)
    subprocess.run(["pkill", "-f", "leads/bot.py"], capture_output=True)
    subprocess.run(["pkill", "-f", "cloudflared"],  capture_output=True)
    import time; time.sleep(2)
    print("🧹 Cleaned up old processes")


async def main():
    print("🚀 Starting LeadsAPI system...")
    kill_old()

    print("⏳ Starting Cloudflare tunnel...")
    tunnel_task = asyncio.create_task(cloudflare.start_tunnel(config.PORT))
    await asyncio.sleep(6)

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app",
         "--host", "0.0.0.0", "--port", str(config.PORT)]
    )
    print(f"✅ LeadsAPI started on port {config.PORT}")

    bot_proc = subprocess.Popen([sys.executable, "bot.py"])
    print("✅ Telegram bot started")

    def shutdown(sig=None, frame=None):
        print("\n🛑 Shutting down...")
        api_proc.terminate()
        bot_proc.terminate()
        subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        await tunnel_task
    except Exception as e:
        print(f"⚠️ Tunnel error: {e}")

    api_proc.wait()
    bot_proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
