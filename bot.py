import asyncio
import math
import os
import re
import shutil
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from database import db

# Progress updates-ஐ track பண்ண Global Dictionary
PROGRESS_CACHE = {}


# ----------------- DUMMY HTTP SERVER -----------------
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running Successfully!")


def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


threading.Thread(target=run_web_server, daemon=True).start()

# ----------------- PYROGRAM CLIENT -----------------
app = Client(
    "MediaAdvancedBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)


# ----------------- FIXED PROGRESS BAR -----------------
async def progress_bar(current, total, status_text, start_time, message):
    now = time.time()
    diff = now - start_time

    # FloodWait வராமல் இருக்க 3 வினாடிகளுக்கு ஒருமுறை மட்டும் Text Edit ஆகும்
    msg_id = message.id
    last_update = PROGRESS_CACHE.get(msg_id, 0)

    if (now - last_update < 3) and (current != total):
        return

    PROGRESS_CACHE[msg_id] = now
    percentage = current * 100 / total
    speed = current / diff if diff > 0 else 0
    time_to_completion = round((total - current) / speed) if speed > 0 else 0

    progress = "[{0}{1}] {2}%\n".format(
        "".join(["▰" for _ in range(math.floor(percentage / 10))]),
        "".join(["▱" for _ in range(10 - math.floor(percentage / 10))]),
        round(percentage, 1),
    )

    tmp = (
        f"**{status_text}**\n\n"
        + progress
        + f"**Speed:** {round(speed / 1024 / 1024, 2)} MB/s\n"
        + f"**Done:** {round(current / 1024 / 1024, 2)} MB / {round(total / 1024 / 1024, 2)} MB\n"
        + f"**ETA:** {time_to_completion}s"
    )

    try:
        await message.edit_text(tmp)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except MessageNotModified:
        pass
    except Exception:
        pass


async def get_video_duration(input_file):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_file,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0


async def get_file_streams(input_file):
    import json

    cmd_json = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        input_file,
    ]
    proc_j = await asyncio.create_subprocess_exec(
        *cmd_json, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout_j, _ = await proc_j.communicate()
    try:
        data = json.loads(stdout_j.decode())
        return data.get("streams", [])
    except:
        return []


def get_drawtext_filter(text, pos="bottom_right", fontsize="24"):
    positions = {
        "top_left": "x=15:y=15",
        "top_right": "x=w-tw-15:y=15",
        "bottom_left": "x=15:y=h-th-15",
        "bottom_right": "x=w-tw-15:y=h-th-15",
        "center": "x=(w-tw)/2:y=(h-th)/2",
    }
    xy = positions.get(pos, positions["bottom_right"])
    return f"drawtext=text='{text}':fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.5:boxborderw=5:{xy}"


# ----------------- COMMANDS -----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"👋 Hello {message.from_user.first_name}!\n\n"
        "I am an advanced Media Swiss-Knife Bot.\n"
        "Send me any Video/File to process Metadata, Streams, Watermark, Zip, or Auto-Rename!"
    )


# ----------------- MEDIA PROCESSOR -----------------
@app.on_message((filters.video | filters.document) & filters.private)
async def handle_media(client, message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎬 Stream Tools", callback_data="tools_stream"
            ),
            InlineKeyboardButton(
                "🏷️ Rename / Auto-Rename", callback_data="tools_rename"
            ),
        ],
        [
            InlineKeyboardButton(
                "💧 Watermark Video", callback_data="tools_watermark"
            ),
            InlineKeyboardButton(
                "📦 Zip / Split", callback_data="tools_zipsplit"
            ),
        ],
    ])
    await message.reply_text(
        "⚙️ **Choose the action you want to perform:**",
        reply_markup=keyboard,
        quote=True,
    )


# ----------------- CALLBACK BUTTONS -----------------
@app.on_callback_query()
async def cb_handler(client, query):
    data = query.data
    user_id = query.from_user.id
    msg = query.message.reply_to_message

    if data == "tools_stream":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎵 Select & Remove Audio", callback_data="select_rm_audio"
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 Select & Remove Subtitle", callback_data="select_rm_sub"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Remove ALL Audio", callback_data="rm_all_audio"
                ),
                InlineKeyboardButton(
                    "❌ Remove ALL Subtitle", callback_data="rm_all_sub"
                ),
            ],
        ])
        await query.message.edit_text(
            "⚙️ **Stream Processing Tools:**", reply_markup=kb
        )

    # STREAM SELECTION & REMOVAL
    elif data in ["select_rm_audio", "select_rm_sub"]:
        stype = "audio" if data == "select_rm_audio" else "subtitle"
        status = await query.message.edit_text(
            f"📥 Downloading video to inspect {stype} streams..."
        )

        start_time = time.time()
        file_path = await client.download_media(
            msg,
            progress=progress_bar,
            progress_args=("📥 Downloading Video...", start_time, status),
        )

        streams = await get_file_streams(file_path)
        target_streams = [
            s
            for s in streams
            if s.get("codec_type") == ("audio" if stype == "audio" else "subtitle")
        ]

        if not target_streams:
            if os.path.exists(file_path):
                os.remove(file_path)
            return await status.edit_text(
                f"❌ No {stype} streams found in this video!"
            )

        buttons = []
        # Save file path safely with unique user ID
        clean_path = file_path.replace("downloads/", "")

        for index, s in enumerate(target_streams):
            s_index = s.get("index")
            lang = s.get("tags", {}).get("language", "und")
            codec = s.get("codec_name", "unk")

            btn_text = f"🗑️ Stream #{s_index} [{lang.upper()}] ({codec})"
            # Send file path identifier
            buttons.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"rmstr_{stype}_{s_index}_{msg.id}",
                )
            ])

        buttons.append([
            InlineKeyboardButton("🔙 Cancel", callback_data="cancel_action")
        ])
        await status.edit_text(
            f" Choose which **{stype.upper()}** stream to remove:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data.startswith("rmstr_"):
        parts = data.split("_")
        stype = parts[1]
        s_index = parts[2]
        msg_id = parts[3]

        file_path = f"downloads/{msg.id}.mp4"  # Default pyrogram download folder structure check
        if not os.path.exists(file_path):
            # Fallback file lookup
            for f in os.listdir("downloads"):
                if f.startswith(str(msg_id)):
                    file_path = os.path.join("downloads", f)
                    break

        status = await query.message.edit_text(
            f"⚙️ Removing Stream #{s_index}..."
        )
        output_path = f"processed_{msg_id}.mp4"

        cmd = f'ffmpeg -i "{file_path}" -map 0 -map -0:{s_index} -c copy "{output_path}" -y'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

        if os.path.exists(file_path):
            os.remove(file_path)

        if os.path.exists(output_path):
            await status.edit_text(
                f"✅ Stream #{s_index} removed!\n\n**Select action:**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🚀 Direct Upload",
                        callback_data=f"direct_upload_{output_path}",
                    )
                ]]),
            )
        else:
            await status.edit_text("❌ Stream Removal Failed!")

    # WATERMARK PROCESS WITH PROGRESS BAR
    elif data == "tools_watermark":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📝 Text Watermark", callback_data="apply_text_watermark"
            )
        ]])
        await query.message.edit_text(
            "💧 **Watermark Processor:**", reply_markup=kb
        )

    elif data == "apply_text_watermark":
        status = await query.message.edit_text("📥 Downloading Video...")
        start_time = time.time()
        file_path = await client.download_media(
            msg,
            progress=progress_bar,
            progress_args=("📥 Downloading...", start_time, status),
        )

        wm_text = await db.get_wm_text(user_id) or "@Anime_Hub_Tamil"
        wm_pos = await db.get_wm_pos(user_id) or "bottom_right"
        wm_size = await db.get_wm_size(user_id) or "24"

        output_path = f"wm_{msg.id}.mp4"
        vf_filter = get_drawtext_filter(wm_text, wm_pos, wm_size)
        total_duration = await get_video_duration(file_path)

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            file_path,
            "-vf",
            vf_filter,
            "-preset",
            "ultrafast",
            "-c:a",
            "copy",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        last_percent = -1
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore")
            time_match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line_str)

            if time_match and total_duration > 0:
                hours, minutes, seconds = map(float, time_match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds
                percentage = int((current_time / total_duration) * 100)

                if percentage >= last_percent + 5:
                    last_percent = percentage
                    filled = "▰" * (percentage // 10)
                    empty = "▱" * (10 - (percentage // 10))
                    try:
                        await status.edit_text(
                            f"💧 **Watermarking...**\n\n[{filled}{empty}] {percentage}%\n"
                        )
                    except:
                        pass

        await proc.wait()

        if os.path.exists(file_path):
            os.remove(file_path)

        if os.path.exists(output_path):
            await status.edit_text(
                "✅ Watermark Added Successfully!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🚀 Direct Upload",
                        callback_data=f"direct_upload_{output_path}",
                    )
                ]]),
            )
        else:
            await status.edit_text("❌ Watermarking Failed.")

    # DIRECT UPLOAD FIX
    elif data.startswith("direct_upload_"):
        output_path = data.replace("direct_upload_", "")
        status = await query.message.edit_text("📤 Uploading File...")
        start_time = time.time()

        thumb_id = await db.get_thumb(user_id)
        thumb_path = (
            await client.download_media(thumb_id) if thumb_id else None
        )

        try:
            await client.send_document(
                chat_id=user_id,
                document=output_path,
                thumb=thumb_path,
                progress=progress_bar,
                progress_args=("📤 Uploading File...", start_time, status),
            )
            await status.delete()
        except Exception as e:
            await status.edit_text(f"❌ Upload Failed: `{str(e)}`")
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "**Available Commands:**\n\n"
        "/set_thumb - Reply to an image to set custom thumbnail\n"
        "/get_thumb - View your current saved thumbnail\n"
        "/del_thumb - Delete your current thumbnail\n"
        "/set_autorename - Set auto rename pattern (e.g. /set_autorename [S01E01])\n"
        "/get_autorename - Check current auto rename pattern\n"
        "/del_autorename - Clear current auto rename pattern\n"
        "/set_wm_text - Set watermark text\n"
        "/wm_pos - Set watermark position (top_left, top_right, bottom_left, bottom_right, center)\n"
        "/wm_size - Set watermark scale/font size (e.g. /wm_size 15)\n"
        "/del_wm_text - Reset watermark text to default"
    )

@app.on_message(filters.command("set_thumb"))
async def set_thumb_cmd(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ Reply to a photo with /set_thumb")
    file_id = message.reply_to_message.photo.file_id
    await db.set_thumb(message.from_user.id, file_id)
    await message.reply_text("✅ Thumbnail saved!")

@app.on_message(filters.command("get_thumb"))
async def get_thumb_cmd(client, message):
    thumb_id = await db.get_thumb(message.from_user.id)
    if not thumb_id:
        return await message.reply_text("❌ No thumbnail saved yet.")
    await message.reply_photo(thumb_id, caption="🖼️ Your saved thumbnail")

@app.on_message(filters.command("del_thumb"))
async def del_thumb_cmd(client, message):
    await db.set_thumb(message.from_user.id, None)
    await message.reply_text("🗑️ Thumbnail deleted.")

@app.on_message(filters.command("set_autorename"))
async def set_autorename_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /set_autorename [S01E01]")
    pattern = message.text.split(None, 1)[1]
    await db.set_auto_rename(message.from_user.id, pattern)
    await message.reply_text(f"✅ Auto-rename pattern set:\n`{pattern}`")

@app.on_message(filters.command("get_autorename"))
async def get_autorename_cmd(client, message):
    pattern = await db.get_auto_rename(message.from_user.id)
    if not pattern:
        return await message.reply_text("❌ No auto-rename pattern set.")
    await message.reply_text(f"📝 Current pattern:\n`{pattern}`")

@app.on_message(filters.command("del_autorename"))
async def del_autorename_cmd(client, message):
    await db.set_auto_rename(message.from_user.id, None)
    await message.reply_text("🗑️ Auto-rename pattern cleared.")

@app.on_message(filters.command("set_wm_text"))
async def set_wm_text_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /set_wm_text Your Text Here")
    text = message.text.split(None, 1)[1]
    await db.set_wm_text(message.from_user.id, text)
    await message.reply_text(f"✅ Watermark text set to:\n`{text}`")

@app.on_message(filters.command("del_wm_text"))
async def del_wm_text_cmd(client, message):
    await db.set_wm_text(message.from_user.id, None)
    await message.reply_text("🗑️ Watermark text reset to default.")

@app.on_message(filters.command("wm_pos"))
async def wm_pos_cmd(client, message):
    valid = ["top_left", "top_right", "bottom_left", "bottom_right", "center"]
    if len(message.command) < 2 or message.command[1] not in valid:
        return await message.reply_text("⚠️ Usage: /wm_pos <position>\nValid: " + ", ".join(valid))
    await db.set_wm_pos(message.from_user.id, message.command[1])
    await message.reply_text(f"✅ Watermark position set to: {message.command[1]}")

@app.on_message(filters.command("wm_size"))
async def wm_size_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text("⚠️ Usage: /wm_size 15")
    await db.set_wm_size(message.from_user.id, message.command[1])
    await message.reply_text(f"✅ Watermark size set to: {message.command[1]}")

if __name__ == "__main__":
    app.run()
    
