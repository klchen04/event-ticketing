import boto3
from botocore.exceptions import ClientError


def create_event(table, event_id, name, capacity):
    table.put_item(
        Item={
            "event_id": event_id,
            "name": name,
            "capacity": capacity,
            "tickets_left": capacity,
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