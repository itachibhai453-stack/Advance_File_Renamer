import os

class Config:
    API_ID = int(os.environ.get("API_ID", "12345678"))
    API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
    
    # MongoDB Connection URL (e.g. mongodb+srv://user:pass@cluster.mongodb.net/myFirstDatabase)
    MONGO_URL = os.environ.get("MONGO_URL", "YOUR_MONGODB_URI")
    
    DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "./downloads")
  
