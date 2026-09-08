import os

class Config:
    API_ID = int(os.environ.get("API_ID", "1234567"))
    API_HASH = os.environ.get("API_HASH", "your_api_hash")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
    DB_URL = os.environ.get("DB_URL", "mongodb+srv://...")
    DB_NAME = os.environ.get("DB_NAME", "MediaBotDB")
    
    # Default Watermark Settings
    DEFAULT_WM_POSITION = "bottom_right" # top_left, top_right, bottom_left, bottom_right, center
    DEFAULT_WM_SIZE = 15 # Percentage of video width
