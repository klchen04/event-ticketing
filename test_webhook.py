import hashlib
import hmac
import json
import time

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

import main
from inventory import create_event, create_order

SECRET = "whsec_test_secret"


@pytest.fixture
def tables(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
        for name, key in [
            ("Events", "event_id"),
            ("Orders", "order_id"),
            ("ProcessedWebhooks", "event_id"),
        ]:
            dynamodb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        yield (
            dynamodb.Table("Events"),
            dynamodb.Table("Orders"),
            dynamodb.Table("ProcessedWebhooks"),
        )


def signed_request(event_id, event_type, order_id):
    payload = json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
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
        SECRET.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256
    ).hexdigest()
    headers = {
        "Stripe-Signature": f"t={timestamp},v1={digest}",
        "Content-Type": "application/json",
    }
    return payload, headers


def tickets_left(events, event_id):
    return events.get_item(Key={"event_id": event_id})["Item"]["tickets_left"]


def test_paid_webhook_marks_order_paid(tables):
    events, orders, _ = tables
    create_event(events, "concert", "Test Concert", capacity=2)
    order_id = create_order(events, orders, "concert", 1)
    client = TestClient(main.app)

    payload, headers = signed_request("evt_1", "checkout.session.completed", order_id)
    response = client.post("/webhook", content=payload, headers=headers)

    assert response.status_code == 200
    assert orders.get_item(Key={"order_id": order_id})["Item"]["status"] == "paid"


def test_repeated_webhook_is_ignored(tables):
    events, orders, _ = tables
    create_event(events, "concert", "Test Concert", capacity=2)
    order_id = create_order(events, orders, "concert", 1)
    client = TestClient(main.app)

    payload, headers = signed_request("evt_1", "checkout.session.completed", order_id)
    first = client.post("/webhook", content=payload, headers=headers)
    second = client.post("/webhook", content=payload, headers=headers)

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "duplicate"


def test_expired_webhook_releases_tickets_once(tables):
    events, orders, _ = tables
    create_event(events, "concert", "Test Concert", capacity=2)
    order_id = create_order(events, orders, "concert", 2)
    client = TestClient(main.app)
    assert tickets_left(events, "concert") == 0

    payload, headers = signed_request("evt_1", "checkout.session.expired", order_id)
    client.post("/webhook", content=payload, headers=headers)
    assert tickets_left(events, "concert") == 2

    # a different event ID for the same order must not release tickets again
    payload, headers = signed_request("evt_2", "checkout.session.expired", order_id)
    client.post("/webhook", content=payload, headers=headers)
    assert tickets_left(events, "concert") == 2


def test_bad_signature_is_rejected(tables):
    client = TestClient(main.app)
    payload, headers = signed_request("evt_1", "checkout.session.completed", "order_x")
    headers["Stripe-Signature"] = "t=1,v1=bad"

    response = client.post("/webhook", content=payload, headers=headers)

    assert response.status_code == 400