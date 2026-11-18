import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb", region_name="us-east-2")

TABLES = {
    "Events": "event_id",
    "Orders": "order_id",
    "ProcessedWebhooks": "event_id",
    "Tickets": "ticket_id",
}

for name, key in TABLES.items():
    try:
        dynamodb.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"Created {name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"{name} already exists")
        else:
            raise