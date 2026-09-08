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
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from database import db


# ----------------- DUMMY HTTP SERVER FOR RENDER -----------------
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


# ----------------- HELPER FUNCTIONS -----------------
async def get_video_duration(input_file):
    """FFprobe பயன்படுத்தி Video-வின் மொத்த நேரத்தை (Seconds) கண்டறிதல்"""
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
    """Audio மற்றும் Subtitle ஸ்ட்ரீம்களை கண்டறிந்து விவரங்களை எடுத்தல்"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name:stream_tags=language,title",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_file,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()

    lines = stdout.decode().strip().split("\n")
    streams = []
    current_stream = {}

    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            current_stream[key] = value
            if key == "codec_type" and len(current_stream) > 1:
                pass
        else:
            if current_stream:
                streams.append(current_stream)
                current_stream = {}

    # Refined Parsing Logic
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

    import json

    data = json.loads(stdout_j.decode())
    return data.get("streams", [])


# ----------------- PROGRESS BAR UTILITY (For Telegram Download/Upload) -----------------
async def progress_bar(current, total, status_text, start_time, message):
    now = time.time()
    diff = now - start_time
    if round(diff % 5) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        elapsed_time = round(diff)
        time_to_completion = (
            round((total - current) / speed) if speed > 0 else 0
        )

        progress = "[{0}{1}] {2}%\n".format(
            "".join(["▰" for _ in range(math.floor(percentage / 10))]),
            "".join(["▱" for _ in range(10 - math.floor(percentage / 10))]),
            round(percentage, 2),
        )

        tmp = (
            progress
            + f"**Speed:** {round(speed / 1024 / 1024, 2)} MB/s\n"
            + f"**Done:** {round(current / 1024 / 1024, 2)} MB / {round(total / 1024 / 1024, 2)} MB\n"
            + f"**ETA:** {time_to_completion}s"
        )

        try:
            await message.edit_text(f"**{status_text}**\n\n{tmp}")
        except:
            pass


# ----------------- WATERMARK HELPERS -----------------
def get_drawtext_filter(text, pos="bottom_right", fontsize="24"):
    positions = {
        "top_left": "x=15:y=15",
        "top_right": "x=w-tw-15:y=15",
        "bottom_left": "x=15:y=h-th-15",
        "bottom_right": "x=w-tw-15:y=h-th-15",
        "center": "x=(w-tw)/2:y=(h-th)/2",
    }
    xy = positions.get(pos, positions["bottom_right"])
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if os.path.exists(font_path):
        return f"drawtext=fontfile='{font_path}':text='{text}':fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.5:boxborderw=5:{xy}"
    return f"drawtext=text='{text}':fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.5:boxborderw=5:{xy}"


# ----------------- COMMAND HANDLERS -----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text(
        f"👋 Hello {message.from_user.first_name}!\n\n"
        "I am an advanced Media Swiss-Knife Bot.\n"
        "Send me any Video/File to process Metadata, Streams, Watermark, Zip, or Auto-Rename!"
    )


@app.on_message(filters.command("set_thumb") & filters.private)
async def set_thumbnail(client, message):
    if message.reply_to_message and message.reply_to_message.photo:
        thumb_id = message.reply_to_message.photo.file_id
        await db.set_thumb(message.from_user.id, thumb_id)
        await message.reply_text("✅ Custom Thumbnail saved successfully!")
    else:
        await message.reply_text(
            "⚠️ Reply to an image with `/set_thumb` to save it."
        )


@app.on_message(filters.command("set_autorename") & filters.private)
async def set_auto_rename_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ Usage: `/set_autorename [Episode_{ep}_1080p]`"
        )
    pattern = message.text.split(None, 1)[1]
    await db.set_auto_rename(message.from_user.id, pattern)
    await message.reply_text(f"✅ Auto-Rename Pattern set to: `{pattern}`")


# ----------------- WATERMARK COMMANDS -----------------
@app.on_message(filters.command("set_wm_text") & filters.private)
async def set_watermark_text(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Usage:** `/set_wm_text @Anime_Hub_Tamil`"
        )
    text = message.text.split(None, 1)[1]
    await db.set_wm_text(message.from_user.id, text)
    await message.reply_text(f"✅ **Watermark Text Saved:** `{text}`")


@app.on_message(filters.command("wm_pos") & filters.private)
async def set_watermark_pos(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Usage:** `/wm_pos [top_left | top_right | bottom_left | bottom_right | center]`"
        )
    pos = message.command[1].lower()
    valid_positions = [
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "center",
    ]
    if pos not in valid_positions:
        return await message.reply_text(
            "❌ Invalid position! Choose from: `top_left`, `top_right`, `bottom_left`, `bottom_right`, `center`"
        )
    await db.set_wm_pos(message.from_user.id, pos)
    await message.reply_text(f"✅ **Watermark Position set to:** `{pos}`")


@app.on_message(filters.command("wm_size") & filters.private)
async def set_watermark_size(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Usage:** `/wm_size 24` (Font size for text)"
        )
    size = message.command[1]
    await db.set_wm_size(message.from_user.id, size)
    await message.reply_text(f"✅ **Watermark Size set to:** `{size}`")


@app.on_message(filters.command("unzip") & filters.private)
async def unzip_file(client, message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply_text(
            "⚠️ **Usage:** Reply to a `.zip` file with `/unzip` command!"
        )

    target_msg = message.reply_to_message
    file_name = target_msg.document.file_name or "archive.zip"

    if not file_name.endswith(".zip"):
        return await message.reply_text("❌ Please reply to a valid `.zip` file!")

    status = await message.reply_text("📥 Downloading ZIP file...")
    start_time = time.time()

    zip_path = await client.download_media(
        target_msg,
        progress=progress_bar,
        progress_args=("📥 Downloading ZIP...", start_time, status),
    )

    extract_dir = f"extracted_{message.id}"
    os.makedirs(extract_dir, exist_ok=True)

    await status.edit_text("📦 Extracting ZIP contents...")

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        await status.edit_text("📤 Uploading extracted files...")

        extracted_count = 0
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                file_full_path = os.path.join(root, file)
                upload_start = time.time()

                await client.send_document(
                    chat_id=message.chat.id,
                    document=file_full_path,
                    caption=f"📁 `{file}`",
                    progress=progress_bar,
                    progress_args=(
                        f"📤 Uploading {file}...",
                        upload_start,
                        status,
                    ),
                )
                extracted_count += 1

        await status.edit_text(
            f"✅ Extracted and uploaded **{extracted_count}** files successfully!"
        )

    except Exception as e:
        await status.edit_text(f"❌ Error during unzip: `{str(e)}`")

    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)


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
        [
            InlineKeyboardButton(
                "📝 Edit Metadata", callback_data="tools_metadata"
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

    # ----------------- STREAM SELECT & REMOVE -----------------
    elif data in ["select_rm_audio", "select_rm_sub"]:
        stype = "audio" if data == "select_rm_audio" else "subtitle"
        status = await query.message.edit_text(
            f"🔍 Analyzing {stype} streams in video..."
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
        for index, s in enumerate(target_streams):
            s_index = s.get("index")
            lang = s.get("tags", {}).get("language", "Unknown")
            title = s.get("tags", {}).get("title", f"Track {index + 1}")
            codec = s.get("codec_name", "Unknown")

            btn_text = f"🗑️ Stream #{s_index} [{lang.upper()}] ({codec})"
            # Format: rmstream_TYPE_STREAMINDEX_FILEPATH
            buttons.append([
                InlineKeyboardButton(
                    btn_text, callback_data=f"rmstr_{stype}_{s_index}"
                )
            ])

        buttons.append([InlineKeyboardButton("🔙 Cancel", callback_data="cancel_action")])

        # Save temporary path in global or local context (or use bot session)
        app.temp_filepath = file_path
        await status.edit_text(
            f" Choose which **{stype.upper()}** stream to remove:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data.startswith("rmstr_"):
        _, stype, s_index = data.split("_")
        file_path = getattr(app, "temp_filepath", None)

        if not file_path or not os.path.exists(file_path):
            return await query.message.edit_text(
                "❌ Session expired! Please try again."
            )

        status = await query.message.edit_text(
            f"⚙️ Removing Stream #{s_index}..."
        )
        output_path = f"processed_{msg.id}.mp4"

        # FFmpeg command to map all EXCEPT selected stream (-map -0:s_index)
        cmd = f'ffmpeg -i "{file_path}" -map 0 -map -0:{s_index} -c copy "{output_path}" -y'

        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

        if os.path.exists(file_path):
            os.remove(file_path)

        if os.path.exists(output_path):
            await status.edit_text(
                f"✅ Stream #{s_index} removed successfully!\n\n**Select next action:**",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✏️ Custom Rename",
                            callback_data=f"do_rename_{output_path}",
                        ),
                        InlineKeyboardButton(
                            "🤖 Apply Auto-Rename",
                            callback_data=f"do_autorename_{output_path}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🚀 Direct Upload",
                            callback_data=f"direct_upload_{output_path}",
                        )
                    ],
                ]),
            )
        else:
            await status.edit_text("❌ Failed to remove stream.")

    elif data == "rm_all_audio":
        status = await query.message.edit_text("📥 Downloading file...")
        start_time = time.time()
        file_path = await client.download_media(
            msg,
            progress=progress_bar,
            progress_args=("📥 Downloading...", start_time, status),
        )

        output_path = f"no_audio_{msg.id}.mp4"
        cmd = f'ffmpeg -i "{file_path}" -an -c:v copy "{output_path}" -y'

        await status.edit_text("⚙️ Removing All Audio Streams...")
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

        if os.path.exists(file_path):
            os.remove(file_path)
        await status.edit_text(
            "✅ All Audios removed!\n\n**Select next action:**",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🚀 Direct Upload",
                        callback_data=f"direct_upload_{output_path}",
                    )
                ]
            ]),
        )

    elif data == "rm_all_sub":
        status = await query.message.edit_text("📥 Downloading file...")
        start_time = time.time()
        file_path = await client.download_media(
            msg,
            progress=progress_bar,
            progress_args=("📥 Downloading...", start_time, status),
        )

        output_path = f"no_sub_{msg.id}.mp4"
        cmd = f'ffmpeg -i "{file_path}" -sn -c:v copy -c:a copy "{output_path}" -y'

        await status.edit_text("⚙️ Removing All Subtitle Streams...")
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

        if os.path.exists(file_path):
            os.remove(file_path)
        await status.edit_text(
            "✅ All Subtitles removed!\n\n**Select next action:**",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🚀 Direct Upload",
                        callback_data=f"direct_upload_{output_path}",
                    )
                ]
            ]),
        )

    # ----------------- WATERMARK WITH REALTIME PROGRESS BAR -----------------
    elif data == "tools_watermark":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📝 Text Watermark", callback_data="apply_text_watermark"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ Watermark Settings", callback_data="wm_settings_info"
                )
            ],
        ])
        await query.message.edit_text(
            "💧 **Watermark Processor:**\nSelect watermark type to apply:",
            reply_markup=kb,
        )

    elif data == "wm_settings_info":
        await query.message.edit_text(
            "⚙️ **Watermark Commands:**\n\n"
            "• `/set_wm_text @Anime_Hub_Tamil` - Set Text Watermark\n"
            "• `/wm_pos top_right` - Position (`top_left`, `top_right`, `bottom_left`, `bottom_right`, `center`)\n"
            "• `/wm_size 24` - Set Font Size (default: 24)"
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

        # Video Total Duration Calculation
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

        # Real-time FFmpeg Progress Parser
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
                percentage = min(percentage, 100)

                if percentage >= last_percent + 5:
                    last_percent = percentage
                    filled = "▰" * (percentage // 10)
                    empty = "▱" * (10 - (percentage // 10))
                    progress_text = (
                        f"💧 **Watermark Adding...**\n\n"
                        f"[{filled}{empty}] {percentage}%\n"
                    )
                    try:
                        await status.edit_text(progress_text)
                    except:
                        pass

        await proc.wait()

        if os.path.exists(file_path):
            os.remove(file_path)

        if os.path.exists(output_path):
            await status.edit_text(
                "✅ Watermark Added Successfully!\n\n**Select next action:**",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✏️ Custom Rename",
                            callback_data=f"do_rename_{output_path}",
                        ),
                        InlineKeyboardButton(
                            "🤖 Auto Rename",
                            callback_data=f"do_autorename_{output_path}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🚀 Direct Upload",
                            callback_data=f"direct_upload_{output_path}",
                        )
                    ],
                ]),
            )
        else:
            await status.edit_text(
                "❌ Watermarking failed. Please check video codec or settings."
            )

    elif data.startswith("direct_upload_"):
        output_path = data.split("_", 2)[2]
        status = await query.message.edit_text("📤 Uploading file...")
        start_time = time.time()

        thumb_id = await db.get_thumb(user_id)
        thumb_path = (
            await client.download_media(thumb_id) if thumb_id else None
        )

        await client.send_document(
            chat_id=user_id,
            document=output_path,
            thumb=thumb_path,
            progress=progress_bar,
            progress_args=("📤 Uploading...", start_time, status),
        )

        if os.path.exists(output_path):
            os.remove(output_path)
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        await status.delete()

    elif data == "cancel_action":
        file_path = getattr(app, "temp_filepath", None)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        await query.message.edit_text("❌ Action Cancelled.")


if __name__ == "__main__":
    app.run()
    
