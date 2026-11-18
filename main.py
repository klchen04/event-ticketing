import io
import os
import time

import qrcode
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from db import get_tables, get_tickets_table
from inventory import (
    check_in,
    create_order,
    forget_webhook_event,
    issue_tickets,
    mark_paid,
    record_webhook_event,
    release_order,
    ticket_ids_for,
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
            success_url=f"{BASE_URL}/orders/{order_id}/tickets",
            cancel_url=f"{BASE_URL}/cancel",
            expires_at=int(time.time()) + 31 * 60,
            metadata={"order_id": order_id},
        )
    except Exception:
        release_order(events, orders, order_id)  # give the held tickets back
        raise HTTPException(status_code=502, detail="Could not start checkout")

    return {"order_id": order_id, "checkout_url": session.url}


@app.get("/cancel")
def cancel():
    return {"message": "Checkout cancelled. Your hold expires on its own."}


@app.get("/orders/{order_id}/tickets", response_class=HTMLResponse)
def order_tickets(order_id: str):
    _, orders, _ = get_tables()
    order = orders.get_item(Key={"order_id": order_id}).get("Item")
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "expired":
        return HTMLResponse("<p>This order expired. Please start a new checkout.</p>")
    if order["status"] != "paid":
        # The webhook can arrive a moment after the redirect, so wait and retry.
        return HTMLResponse(
            '<meta http-equiv="refresh" content="2">'
            "<p>Confirming your payment... this page will refresh.</p>"
        )
    images = "".join(
        f'<div><img src="/tickets/{tid}/qr.png" width="200"><p>{tid}</p></div>'
        for tid in ticket_ids_for(order_id, order["quantity"])
    )
    return HTMLResponse(f"<h1>Your tickets</h1>{images}")


@app.get("/tickets/{ticket_id}/qr.png")
def ticket_qr(ticket_id: str):
    ticket = get_tickets_table().get_item(Key={"ticket_id": ticket_id}).get("Item")
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    buffer = io.BytesIO()
    qrcode.make(ticket_id).save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@app.post("/checkin/{ticket_id}")
def checkin(ticket_id: str):
    result = check_in(get_tickets_table(), ticket_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Ticket not found")
    if result == "already_used":
        raise HTTPException(status_code=409, detail="Ticket already used")
    return {"status": "checked in"}


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
            order_id = session["metadata"]["order_id"]
            mark_paid(orders, order_id)
            order = orders.get_item(Key={"order_id": order_id})["Item"]
            if order["status"] == "paid":
                issue_tickets(
                    get_tickets_table(), order_id, order["event_id"], order["quantity"]
                )
        elif event["type"] == "checkout.session.expired":
            release_order(events, orders, session["metadata"]["order_id"])
    except Exception:
        forget_webhook_event(webhooks, event["id"])  # so Stripe's retry can try again
        raise

    return {"status": "ok"}