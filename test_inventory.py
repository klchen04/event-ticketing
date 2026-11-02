import boto3
import pytest
from moto import mock_aws

from inventory import create_event, reserve_tickets


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