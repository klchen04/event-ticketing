import boto3
import pytest
from moto import mock_aws

from inventory import create_event, reserve_tickets, create_order, mark_paid, release_order


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        yield dynamodb.create_table(
            TableName="Events",
            KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


def test_cannot_oversell(table):
    create_event(table, "concert", "Test Concert", capacity=3)
    assert reserve_tickets(table, "concert", 2) is True
    assert reserve_tickets(table, "concert", 2) is False  # only 1 left
    assert reserve_tickets(table, "concert", 1) is True
    assert reserve_tickets(table, "concert", 1) is False  # sold out
    item = table.get_item(Key={"event_id": "concert"})["Item"]
    assert item["tickets_left"] == 0


@pytest.fixture
def orders_table(table):
    dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    return dynamodb.create_table(
        TableName="Orders",
        KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def test_paid_order_is_only_processed_once(table, orders_table):
    create_event(table, "concert", "Test Concert", capacity=2)
    order_id = create_order(table, orders_table, "concert", 1)
    assert order_id is not None
    assert mark_paid(orders_table, order_id) is True
    assert mark_paid(orders_table, order_id) is False  # a repeated webhook does nothing


def test_released_order_gives_tickets_back_once(table, orders_table):
    create_event(table, "concert", "Test Concert", capacity=2)
    order_id = create_order(table, orders_table, "concert", 2)
    assert table.get_item(Key={"event_id": "concert"})["Item"]["tickets_left"] == 0
    assert release_order(table, orders_table, order_id) is True
    assert release_order(table, orders_table, order_id) is False  # no double release
    assert table.get_item(Key={"event_id": "concert"})["Item"]["tickets_left"] == 2


def test_paid_order_cannot_be_released(table, orders_table):
    create_event(table, "concert", "Test Concert", capacity=1)
    order_id = create_order(table, orders_table, "concert", 1)
    mark_paid(orders_table, order_id)
    assert release_order(table, orders_table, order_id) is False
    assert table.get_item(Key={"event_id": "concert"})["Item"]["tickets_left"] == 0