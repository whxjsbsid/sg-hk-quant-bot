import time
import requests

BASE_URL = "https://mock-api.roostoo.com"

def get_one_price(pair="BTC/USD"):
    params = {
        "timestamp": int(time.time() * 1000),  # 13-digit timestamp
        "pair": pair
    }

    response = requests.get(f"{BASE_URL}/v3/ticker", params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    if not data.get("Success"):
        raise ValueError(f"API error: {data.get('ErrMsg')}")

    last_price = data["Data"][pair]["LastPrice"]
    return last_price

if __name__ == "__main__":
    pair = "BTC/USD"
    price = get_one_price(pair)
    print(f"{pair} last price: {price}")
