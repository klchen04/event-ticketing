import boto3
import uuid
from botocore.exceptions import ClientError


def create_event(table, event_id, name, capacity, price_cents=1000):
    table.put_item(
        Item={
            "event_id": event_id,
            "name": name,
            "capacity": capacity,
            "tickets_left": capacity,
            "price_cents": price_cents,
        },
        ConditionExpression="attribute_not_exists(event_id)",
    )


def reserve_tickets(table, event_id, quantity):
    """Take tickets out of inventory. True if it worked, False if not enough are left."""
    try:
        table.update_item(
            Key={"event_id": event_id},
            UpdateExpression="SET tickets_left = tickets_left - :q",
            ConditionExpression="tickets_left >= :q",
            ExpressionAttributeValues={":q": quantity},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def create_order(events_table, orders_table, event_id, quantity):
    """Hold tickets for a new order. Returns the order_id, or None if there aren't enough."""
    if not reserve_tickets(events_table, event_id, quantity):
        return None
    order_id = str(uuid.uuid4())
    orders_table.put_item(
        Item={
            "order_id": order_id,
            "event_id": event_id,
            "quantity": quantity,
            "status": "pending",
        }
    )
    return order_id


def mark_paid(orders_table, order_id):
    """pending -> paid. True the first time, False if it was already handled."""
    return _change_status(orders_table, order_id, "paid")


def release_order(events_table, orders_table, order_id):
    """pending -> expired, and give the tickets back. True only the first time."""
    order = orders_table.get_item(Key={"order_id": order_id}).get("Item")
    if order is None:
        return False
    if not _change_status(orders_table, order_id, "expired"):
        return False
    events_table.update_item(
        Key={"event_id": order["event_id"]},
        UpdateExpression="SET tickets_left = tickets_left + :q",
        ExpressionAttributeValues={":q": order["quantity"]},
    )
    return True


def _change_status(orders_table, order_id, new_status):
    try:
        orders_table.update_item(
            Key={"order_id": order_id},
            UpdateExpression="SET #s = :new",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":new": new_status, ":pending": "pending"},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def record_webhook_event(webhooks_table, event_id):
    """True the first time we see this Stripe event ID, False for repeats."""
    try:
        webhooks_table.put_item(
            Item={"event_id": event_id},
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def forget_webhook_event(webhooks_table, event_id):
    webhooks_table.delete_item(Key={"event_id": event_id})


def ticket_ids_for(order_id, quantity):
    return [f"{order_id}-{n}" for n in range(1, int(quantity) + 1)]


def issue_tickets(tickets_table, order_id, event_id, quantity):
    """One ticket per seat. Safe to call repeatedly, since IDs come from the order ID."""
    ids = ticket_ids_for(order_id, quantity)
    for ticket_id in ids:
        try:
            tickets_table.put_item(
                Item={
                    "ticket_id": ticket_id,
                    "order_id": order_id,
                    "event_id": event_id,
                    "status": "valid",
                },
                ConditionExpression="attribute_not_exists(ticket_id)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return ids


def check_in(tickets_table, ticket_id):
    """'ok' the first time, 'already_used' after that, 'not_found' for unknown tickets."""
    try:
        tickets_table.update_item(
            Key={"ticket_id": ticket_id},
            UpdateExpression="SET #s = :used",
            ConditionExpression="#s = :valid",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":used": "used", ":valid": "valid"},
        )
        return "ok"
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    item = tickets_table.get_item(Key={"ticket_id": ticket_id}).get("Item")
    return "not_found" if item is None else "already_used"