# 🎬 Advanced Media Swiss-Knife Telegram Bot

A powerful Python-based Telegram Bot built with Pyrogram, FFmpeg, and MongoDB. Includes Video Stream Extraction/Removal, Watermarking, Custom Thumbnail, Metadata Editor, Auto-Renamer, Zip Extractor, File Splitter, and Live Progress Bars.

---

## ✨ Features

- 🎵 **Audio Stream Tools**: Extract, Remove, or Add external Audio Streams.
- 💬 **Subtitle Stream Tools**: Extract or Remove Subtitle Streams.
- 💧 **Custom Watermark**: Position (Direction) and Size customization.
- 🏷️ **Metadata & Custom Thumbnail**: Embedded Metadata & Database-saved Custom Thumbnails.
- ✏️ **Rename & Auto-Renamer**: Rename files manually or apply saved patterns automatically post-processing.
- 📦 **Zip & Splitter**: Extract ZIP files and split large videos into smaller parts.
- 📊 **Real-time Progress Bar**: Displays percentage, speed, done MBs, and ETA for upload/download.
- 🗄️ **MongoDB Integration**: Save thumbnails, auto-rename patterns, and user preferences persistently.

---

## 🛠️ Environment Variables

Configure these variables in Render or your hosting provider:

| Variable Name | Description | Example / Default |
| :--- | :--- | :--- |
| `API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org) | `1234567` |
| `API_HASH` | Telegram API Hash from [my.telegram.org](https://my.telegram.org) | `abcdef123456...` |
| `BOT_TOKEN` | Bot Token from [@BotFather](https://t.me/BotFather) | `123456:ABC-DEF1...` |
| `DB_URL` | MongoDB Connection URL String | `mongodb+srv://...` |
| `DB_NAME` | MongoDB Database Name | `MediaBotDB` |

---

## 🚀 Render Docker Deployment (Step-by-Step)

1. **Push to GitHub**:
   Upload all repository files including `Dockerfile`, `bot.py`, `config.py`, `database.py`, and `requirements.txt` to your GitHub repo.

2. **Render Web/Background Worker Setup**:
   - Go to [Render Dashboard](https://dashboard.render.com).
   - Click **New +** -> **Background Worker** (or **Web Service**).
   - Connect your GitHub Repository.
   - Choose **Environment**: `Docker`.
   - Set **Docker Command**: `python bot.py` (or leave default as defined in Dockerfile).

3. **Add Environment Variables**:
   - In Render, navigate to the **Environment** tab of your service.
   - Key-Value pairs-ah `API_ID`, `API_HASH`, `BOT_TOKEN`, `DB_URL`, `DB_NAME` sethukonga.

4. **Deploy**:
   - Click **Create Background Worker** / **Deploy**. Render will automatically build the Docker Image and start the bot.

---

## 📝 License
This project is open-source and free to use.
# bot Commands
start - Check if the bot is alive
set_thumb - Reply to an image to set custom thumbnail
get_thumb - View your current saved thumbnail
del_thumb - Delete your current thumbnail
set_autorename - Set auto rename pattern (e.g. /set_autorename [S01E01])
get_autorename - Check current auto rename pattern
del_autorename - Clear current auto rename pattern
wm_pos - Set watermark position (top_left, top_right, bottom_left, bottom_right, center)
wm_size - Set watermark scale percentage (e.g. /wm_size 15)
help - Show usage guide and stream tool menu
