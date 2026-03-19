from dotenv import load_dotenv
load_dotenv()

from bot.execution.roostoo_client import RoostooClient

client = RoostooClient()

print("EXCHANGE INFO")
print(client.get_exchange_info())

print("\nBALANCE")
print(client.get_balance())

print("\nPENDING COUNT")
print(client.pending_count())

print("\nQUERY ORDERS")
print(client.query_order(pair="BTC/USD"))
