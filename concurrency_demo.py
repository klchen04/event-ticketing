from concurrent.futures import ThreadPoolExecutor

from db import get_tables
from inventory import create_event, reserve_tickets

EVENT_ID = "race-demo"
TICKETS = 5
BUYERS = 20


def fresh_event():
    events, _, _ = get_tables()
    events.delete_item(Key={"event_id": EVENT_ID})
    create_event(events, EVENT_ID, "Race Demo", capacity=TICKETS)


def naive_buy(_n):
    """Read the count, then write it back. This is the classic race condition."""
    events, _, _ = get_tables()
    item = events.get_item(Key={"event_id": EVENT_ID})["Item"]
    if item["tickets_left"] < 1:
        return False
    events.update_item(
        Key={"event_id": EVENT_ID},
        UpdateExpression="SET tickets_left = :new",
        ExpressionAttributeValues={":new": item["tickets_left"] - 1},
    )
    return True


def safe_buy(_n):
    """My implementation: subtract only if enough are left, in one step."""
    events, _, _ = get_tables()
    return reserve_tickets(events, EVENT_ID, 1)


def race(label, buy):
    fresh_event()
    with ThreadPoolExecutor(max_workers=BUYERS) as pool:
        results = list(pool.map(buy, range(BUYERS)))
    events, _, _ = get_tables()
    left = events.get_item(Key={"event_id": EVENT_ID})["Item"]["tickets_left"]
    print(f"{label}: {BUYERS} buyers raced for {TICKETS} tickets")
    print(f"  purchases accepted: {results.count(True)}")
    print(f"  tickets left in database: {left}")


race("Naive read-then-write", naive_buy)
print()
race("Conditional write (my implementation)", safe_buy)