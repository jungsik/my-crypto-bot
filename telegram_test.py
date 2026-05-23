import os

import requests


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN secret is missing.")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID secret is missing.")

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": "GitHub Actions Telegram test OK",
}

response = requests.post(url, json=payload, timeout=10)
print("status_code:", response.status_code)
print("response:", response.text)
response.raise_for_status()
