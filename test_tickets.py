import boto3
import pytest
from moto import mock_aws

from inventory import check_in, issue_tickets


@pytest.fixture
def tickets_table(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-2")
        yield dynamodb.create_table(
            TableName="Tickets",
            KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


def test_issue_tickets_is_safe_to_repeat(tickets_table):
    first = issue_tickets(tickets_table, "order-1", "concert", 2)
    second = issue_tickets(tickets_table, "order-1", "concert", 2)
    assert first == second == ["order-1-1", "order-1-2"]
    assert len(tickets_table.scan()["Items"]) == 2


def test_ticket_can_only_be_checked_in_once(tickets_table):
    issue_tickets(tickets_table, "order-1", "concert", 1)
    assert check_in(tickets_table, "order-1-1") == "ok"
    assert check_in(tickets_table, "order-1-1") == "already_used"


def test_unknown_ticket_is_not_found(tickets_table):
    assert check_in(tickets_table, "nope") == "not_found"