from db import get_tables
from inventory import create_event

events, _, _ = get_tables()
create_event(events, "demo-concert", "Demo Concert", capacity=5, price_cents=2500)
print("Created demo-concert")