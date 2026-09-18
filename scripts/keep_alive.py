"""Automated Cloud Keep-Alive Ping Service for GridWise.

Prevents free-tier cloud containers (Render, Koyeb) from sleeping or cold-starting.
Sends a periodic GET /health ping every 3-5 minutes.

Usage:
    python scripts/keep_alive.py https://<YOUR-DEPLOYED-URL>
"""

import sys
import time
import httpx

DEFAULT_INTERVAL_SECONDS = 240  # 4 minutes


def ping_forever(target_url: str, interval: int = DEFAULT_INTERVAL_SECONDS):
    target_url = target_url.rstrip("/")
    health_url = f"{target_url}/health"
    print(f"🚀 Starting GridWise Keep-Alive Ping Service for {health_url} (Interval: {interval}s)")

    client = httpx.Client(timeout=10.0)
    pings_sent = 0
    failures = 0

    while True:
        try:
            start_t = time.time()
            resp = client.get(health_url)
            elapsed = (time.time() - start_t) * 1000

            if resp.status_code == 200:
                pings_sent += 1
                print(f"[{time.strftime('%X')}] ✅ Health ping #{pings_sent} OK ({elapsed:.1f}ms) — Server awake.")
            else:
                failures += 1
                print(f"[{time.strftime('%X')}] ⚠️ Non-200 response: {resp.status_code} ({resp.text})")
        except Exception as ex:
            failures += 1
            print(f"[{time.strftime('%X')}] ❌ Ping failed: {ex}")

        time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/keep_alive.py <TARGET_BASE_URL>")
        sys.exit(1)

    url = sys.argv[1]
    ping_forever(url)
