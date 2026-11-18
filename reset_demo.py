# Deletes ALL orders, tickets, and webhook records. Demo data only.
from db import get_tables, get_tickets_table


def clear(table, key_name):
    for item in table.scan()["Items"]:
        table.delete_item(Key={key_name: item[key_name]})


events, orders, webhooks = get_tables()
clear(orders, "order_id")
clear(webhooks, "event_id")
clear(get_tickets_table(), "ticket_id")

events.update_item(
    Key={"event_id": "demo-concert"},
    UpdateExpression="SET tickets_left = #c",
    ExpressionAttributeNames={"#c": "capacity"},
)
print("Demo reset: demo-concert is back to full capacity")