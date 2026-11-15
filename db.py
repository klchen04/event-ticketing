import os

import boto3


def get_tables():
    region = os.environ.get("AWS_REGION", "us-east-2")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    return (
        dynamodb.Table("Events"),
        dynamodb.Table("Orders"),
        dynamodb.Table("ProcessedWebhooks"),
    )