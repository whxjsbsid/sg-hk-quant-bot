from dotenv import load_dotenv
load_dotenv()

from bot.execution.roostoo_client import RoostooClient

client = RoostooClient()

print("BEFORE BALANCE")
print(client.get_balance())

print("\nPLACE ORDER")
order = client.place_order(
    pair="BTC/USD",
    side="BUY",
    quantity=0.001,
    order_type="MARKET",
)
print(order)

print("\nAFTER BALANCE")
print(client.get_balance())

print("\nQUERY ORDERS")
print(client.query_order(pair="BTC/USD"))
