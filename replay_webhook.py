import hashlib
import hmac
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

order_id = sys.argv[1]
event_id = sys.argv[2] if len(sys.argv) > 2 else f"evt_replay_{int(time.time())}"
secret = os.environ["STRIPE_WEBHOOK_SECRET"]

payload = json.dumps(
    {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "object": "checkout.session",
                "metadata": {"order_id": order_id},
            }
        },
    }
)
timestamp = int(time.time())
digest = hmac.new(
    secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256
).hexdigest()
headers = {
    "Stripe-Signature": f"t={timestamp},v1={digest}",
    "Content-Type": "application/json",
}

for attempt in (1, 2):
    response = httpx.post("http://localhost:8000/webhook", content=payload, headers=headers)
    print(f"Delivery {attempt}: {response.status_code} {response.json()}")