import requests
import config


def create_qr_third_party(amount: float, user_id: int) -> dict:
    """3rd party API se QR generate"""
    url = f"{config.THIRD_PARTY_API_URL}/paytm/qr.php"
    params = {
        "key": config.THIRD_PARTY_API_KEY,
        "upi": config.THIRD_PARTY_UPI_ID,
        "amount": str(amount)
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data.get("status") == "success":
            return {
                "status": "success",
                "order_id": data.get("order_id"),
                "qr_url": data.get("qr_url")
            }
        return {"status": "failed", "error": data.get("message", "Unknown error")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def verify_payment_third_party(order_id: str) -> dict:
    """3rd party API se payment verify"""
    url = f"{config.THIRD_PARTY_API_URL}/paytm/pay.php"
    params = {
        "key": config.THIRD_PARTY_API_KEY,
        "mid": config.THIRD_PARTY_MID,
        "midkey": config.THIRD_PARTY_MID,
        "oid": order_id
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
        if data.get("status") == "success":
            return {"status": "success", "amount": data.get("amount")}
        return {"status": "failed"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
