import os
import time

import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_tables
from inventory import (
    create_order,
    forget_webhook_event,
    mark_paid,
    record_webhook_event,
    release_order,
)

load_dotenv()
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

app = FastAPI()


class CheckoutRequest(BaseModel):
    quantity: int = Field(ge=1, le=10)


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/events/{event_id}/checkout")
def start_checkout(event_id: str, body: CheckoutRequest):
    events, orders, _ = get_tables()
    event = events.get_item(Key={"event_id": event_id}).get("Item")
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    order_id = create_order(events, orders, event_id, body.quantity)
    if order_id is None:
        raise HTTPException(status_code=409, detail="Not enough tickets left")

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": event["name"]},
                        "unit_amount": int(event["price_cents"]),
                    },
                    "quantity": body.quantity,
                }
            ],
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/cancel",
            expires_at=int(time.time()) + 31 * 60,
            metadata={"order_id": order_id},
        )
    except Exception:
        release_order(events, orders, order_id)  # give the held tickets back
        raise HTTPException(status_code=502, detail="Could not start checkout")

    return {"order_id": order_id, "checkout_url": session.url}


@app.get("/success")
def success():
    return {"message": "Payment received. Your tickets are on the way."}


@app.get("/cancel")
def cancel():
    return {"message": "Checkout cancelled. Your hold expires on its own."}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, os.environ["STRIPE_WEBHOOK_SECRET"]
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook")

    events, orders, webhooks = get_tables()

    if not record_webhook_event(webhooks, event["id"]):
        return {"status": "duplicate"}

    try:
        session = event["data"]["object"]
        if event["type"] == "checkout.session.completed":
            mark_paid(orders, session["metadata"]["order_id"])
        elif event["type"] == "checkout.session.expired":
            release_order(events, orders, session["metadata"]["order_id"])
    except Exception:
        forget_webhook_event(webhooks, event["id"])  # so Stripe's retry can try again
        raise

    return {"status": "ok"}