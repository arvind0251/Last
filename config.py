import os
from dotenv import load_dotenv

load_dotenv()

# Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# 3rd Party Payment API
THIRD_PARTY_API_URL = os.getenv("THIRD_PARTY_API_URL", "https://tusharbairagi.online")
THIRD_PARTY_API_KEY = os.getenv("THIRD_PARTY_API_KEY", "beaf7f50cb4c316b")
THIRD_PARTY_UPI_ID = os.getenv("THIRD_PARTY_UPI_ID", "paytm.s1i5v3t@pty")
THIRD_PARTY_MID = os.getenv("THIRD_PARTY_MID", "FBbU131")

# Database
DB_PATH = os.getenv("DB_PATH", "subscription_bot.db")
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env")
if OWNER_ID == 0:
    raise RuntimeError("❌ OWNER_ID missing in .env")
