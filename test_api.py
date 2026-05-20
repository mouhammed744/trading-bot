"""
Script de diagnostic des clés API Binance.
Lance : python test_api.py
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

key    = os.getenv("BINANCE_API_KEY", "")
secret = os.getenv("BINANCE_API_SECRET", "")

print(f"Clé chargée   : {key[:10]}...{key[-4:]}  (longueur={len(key)})")
print(f"Secret chargé : {secret[:10]}...{secret[-4:]}  (longueur={len(secret)})")
print()

from binance.client import Client

# --- Test 1 : API LIVE ---
print("=== Test API LIVE (binance.com) ===")
try:
    c = Client(key, secret)
    info = c.get_account()
    print("SUCCES — connexion live OK")
    for b in info["balances"]:
        if float(b["free"]) > 0 or float(b["locked"]) > 0:
            print(f"  {b['asset']}: libre={b['free']}  bloqué={b['locked']}")
except Exception as e:
    print(f"ECHEC : {e}")

print()

# --- Test 2 : API TESTNET ---
print("=== Test API TESTNET (testnet.binance.vision) ===")
try:
    c2 = Client(key, secret)
    c2.API_URL = "https://testnet.binance.vision/api"
    info2 = c2.get_account()
    print("SUCCES — connexion testnet OK  (=> tes clés sont des clés TESTNET !)")
    for b in info2["balances"]:
        if float(b["free"]) > 0 or float(b["locked"]) > 0:
            print(f"  {b['asset']}: libre={b['free']}  bloqué={b['locked']}")
except Exception as e:
    print(f"ECHEC : {e}")
