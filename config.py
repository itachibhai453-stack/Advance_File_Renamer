import os
import threading
from flask import Flask

class Config:
    API_ID = int(os.environ.get("API_ID", "12345678"))
    API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
    
    # MongoDB Connection URL (e.g. mongodb+srv://user:pass@cluster.mongodb.net/myFirstDatabase)
    MONGO_URL = os.environ.get("MONGO_URL", "YOUR_MONGODB_URI")
    
    DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "./downloads")
    
    # Render binding panna PORT variable
    PORT = int(os.environ.get("PORT", 10000))

# Web Port Keep-Alive Server
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_web_server():
    app.run(host="0.0.0.0", port=Config.PORT)

# Background Thread-la web server start aagum (Bot crash aagama iruka)
threading.Thread(target=run_web_server, daemon=True).start()
