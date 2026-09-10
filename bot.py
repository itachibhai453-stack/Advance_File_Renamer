import asyncio
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import Config
from database import db


# ============================================================
# SETTINGS
# ============================================================

DOWNLOAD_DIR = Path("downloads")
OUTPUT_DIR = Path("outputs")

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PROGRESS_CACHE = {}
FILE_CACHE = {}

DOWNLOAD_TIMEOUT = 60 * 30       # 30 minutes
FFMPEG_TIMEOUT = 60 * 60 * 3     # 3 hours
PROGRESS_INTERVAL = 3


# ============================================================
# RENDER WEB SERVER
# ============================================================

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is Running Successfully!")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", "8080"))

    server = HTTPServer(
        ("0.0.0.0", port),
        SimpleHTTPRequestHandler
    )

    print(f"[WEB] Server started on port {port}")

    server.serve_forever()


threading.Thread(
    target=run_web_server,
    daemon=True
).start()


# ============================================================
# PYROGRAM
# ============================================================

app = Client(
    "MediaAdvancedBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)


# ============================================================
# SAFE MESSAGE EDIT
# ============================================================

async def safe_edit_message(message, text, reply_markup=None):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup
        )

    except MessageNotModified:
        pass

    except FloodWait as e:
        print(f"[FLOODWAIT] Sleeping {e.value}s")

        await asyncio.sleep(e.value)

        try:
            await message.edit_text(
                text,
                reply_markup=reply_markup
            )
        except Exception as err:
            print(f"[EDIT RETRY ERROR] {err}")

    except Exception as e:
        print(f"[MESSAGE EDIT ERROR] {e}")


# ============================================================
# PROGRESS CALLBACK
# ============================================================

async def progress_bar(
    current,
    total,
    status_text,
    start_time,
    message
):
    """
    IMPORTANT:
    At 100%, this callback DOES NOT perform Telegram edit.

    This prevents download_media() from getting blocked
    by the final Telegram message edit.
    """

    try:

        if not total:
            return

        # ----------------------------------------------------
        # CRITICAL FIX
        # ----------------------------------------------------
        # Do NOT edit Telegram message when current == total.
        #
        # download_media() must be allowed to return first.
        # ----------------------------------------------------

        if current >= total:
            return

        now = time.time()

        last_update = PROGRESS_CACHE.get(message.id, 0)

        if now - last_update < PROGRESS_INTERVAL:
            return

        PROGRESS_CACHE[message.id] = now

        elapsed = max(now - start_time, 0.1)

        percentage = min(
            (current * 100) / total,
            100
        )

        speed = current / elapsed

        remaining = max(total - current, 0)

        eta = int(
            remaining / speed
        ) if speed > 0 else 0

        filled = min(
            int(percentage // 10),
            10
        )

        empty = 10 - filled

        bar = (
            "▰" * filled +
            "▱" * empty
        )

        text = (
            f"**{status_text}**\n\n"
            f"[{bar}] {percentage:.1f}%\n\n"
            f"**Speed:** "
            f"{speed / 1024 / 1024:.2f} MB/s\n"
            f"**Done:** "
            f"{current / 1024 / 1024:.2f} MB / "
            f"{total / 1024 / 1024:.2f} MB\n"
            f"**ETA:** {eta}s"
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # Don't await Telegram edit here.
        # ----------------------------------------------------

        asyncio.create_task(
            safe_edit_message(message, text)
        )

    except Exception as e:
        print(f"[PROGRESS ERROR] {e}")


# ============================================================
# FILE DOWNLOAD
# ============================================================

async def download_file(client, message, status, status_text):
    """
    Safe download wrapper.

    Includes:
    - timeout
    - progress callback
    - existence check
    - file size check
    """

    start_time = time.time()

    try:

        print(
            f"[DOWNLOAD] Starting download "
            f"message_id={message.id}"
        )

        file_path = await asyncio.wait_for(

            client.download_media(
                message,
                file_name=str(DOWNLOAD_DIR) + "/",
                progress=progress_bar,
                progress_args=(
                    status_text,
                    start_time,
                    status
                )
            ),

            timeout=DOWNLOAD_TIMEOUT
        )

    except asyncio.TimeoutError:

        print("[DOWNLOAD] Timeout")

        await safe_edit_message(
            status,
            "❌ **Download Timeout!**\n\n"
            "The file took too long to download."
        )

        return None

    except Exception as e:

        print(f"[DOWNLOAD ERROR] {repr(e)}")

        await safe_edit_message(
            status,
            "❌ **Download Failed!**\n\n"
            f"`{str(e)[:1000]}`"
        )

        return None

    # --------------------------------------------------------
    # CRITICAL CHECK
    # --------------------------------------------------------

    if not file_path:

        await safe_edit_message(
            status,
            "❌ **Download Failed!**\n\n"
            "Pyrogram returned an empty file path."
        )

        return None

    file_path = str(file_path)

    if not os.path.exists(file_path):

        await safe_edit_message(
            status,
            "❌ **Downloaded File Not Found!**\n\n"
            f"`{file_path}`"
        )

        return None

    file_size = os.path.getsize(file_path)

    if file_size <= 0:

        await safe_edit_message(
            status,
            "❌ **Downloaded File Is Empty!**"
        )

        return None

    print(
        f"[DOWNLOAD] Completed: "
        f"{file_path} "
        f"({file_size / 1024 / 1024:.2f} MB)"
    )

    # --------------------------------------------------------
    # THIS EDIT HAPPENS ONLY AFTER download_media RETURNS
    # --------------------------------------------------------

    await safe_edit_message(
        status,
        "✅ **Download Completed!**\n\n"
        f"📁 Size: "
        f"`{file_size / 1024 / 1024:.2f} MB`\n\n"
        "⏳ **Starting processing...**"
    )

    return file_path


# ============================================================
# FFMPEG HELPERS
# ============================================================

async def get_video_duration(input_file):

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_file
    ]

    try:

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(
                "[FFPROBE ERROR]",
                stderr.decode(errors="ignore")
            )
            return 0

        value = stdout.decode().strip()

        return float(value) if value else 0

    except Exception as e:

        print(f"[DURATION ERROR] {e}")

        return 0


async def get_file_streams(input_file):

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        input_file
    ]

    try:

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return []

        data = json.loads(
            stdout.decode(errors="ignore")
        )

        return data.get("streams", [])

    except Exception as e:

        print(f"[STREAM ERROR] {e}")

        return []


# ============================================================
# DRAW TEXT
# ============================================================

def escape_drawtext(text):

    text = str(text)

    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")

    return text


def get_drawtext_filter(
    text,
    position="bottom_right",
    fontsize="24"
):

    text = escape_drawtext(text)

    try:
        fontsize = int(fontsize)
    except Exception:
        fontsize = 24

    fontsize = max(
        8,
        min(fontsize, 200)
    )

    positions = {

        "top_left":
            "x=15:y=15",

        "top_right":
            "x=w-tw-15:y=15",

        "bottom_left":
            "x=15:y=h-th-15",

        "bottom_right":
            "x=w-tw-15:y=h-th-15",

        "center":
            "x=(w-tw)/2:y=(h-th)/2"
    }

    xy = positions.get(
        position,
        positions["bottom_right"]
    )

    return (
        f"drawtext="
        f"text='{text}':"
        f"fontcolor=white:"
        f"fontsize={fontsize}:"
        f"box=1:"
        f"boxcolor=black@0.5:"
        f"boxborderw=5:"
        f"{xy}"
    )


# ============================================================
# FFMPEG RUNNER
# ============================================================

async def run_ffmpeg(
    command,
    status,
    total_duration=0,
    label="Processing"
):
    print("[FFMPEG]", " ".join(map(str, command)))

    process = None

    try:
        process = await asyncio.create_subprocess_exec(
    *command,
    limit=1024 * 1024,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
        )

        last_percent = -1
        stderr_data = []

        while True:
            try:
                line = await process.stderr.readline()
            except ValueError as e:
                print(f"[FFMPEG READ ERROR] {e}")
                continue

            if not line:
                break

            decoded = line.decode(
                "utf-8",
                errors="ignore"
            )

            stderr_data.append(decoded)

            # --------------------------------------------
            # Read FFmpeg progress
            # --------------------------------------------

            if total_duration > 0:

                match = re.search(
                    r"time=(\d+):(\d+):(\d+(?:\.\d+)?)",
                    decoded
                )

                if match:

                    hours = float(match.group(1))
                    minutes = float(match.group(2))
                    seconds = float(match.group(3))

                    current_time = (
                        hours * 3600
                        + minutes * 60
                        + seconds
                    )

                    percentage = int(
                        (current_time / total_duration) * 100
                    )

                    percentage = max(
                        0,
                        min(percentage, 100)
                    )

                    if percentage >= last_percent + 5:

                        last_percent = percentage

                        filled = min(
                            percentage // 10,
                            10
                        )

                        empty = 10 - filled

                        bar = (
                            "▰" * filled
                            + "▱" * empty
                        )

                        await safe_edit_message(
                            status,
                            f"💧 **{label}...**\n\n"
                            f"[{bar}] {percentage}%"
                        )

        await process.wait()

        error_output = "".join(stderr_data)

        if process.returncode != 0:

            print(
                "[FFMPEG FAILED]\n"
                + error_output[-5000:]
            )

            return False, error_output

        print("[FFMPEG] Completed successfully")

        return True, error_output

    except asyncio.CancelledError:

        if process:

            try:
                process.kill()
                await process.wait()
            except Exception:
                pass

        raise

    except Exception as e:

        print(f"[FFMPEG EXCEPTION] {repr(e)}")

        return False, str(e)

            # ------------------------------------------------
            # FFmpeg time=
            # ------------------------------------------------

            if total_duration > 0:

                match = re.search(
                    r"time=(\d+):(\d+):(\d+(?:\.\d+)?)",
                    decoded
                )

                if match:

                    hours = float(match.group(1))
                    minutes = float(match.group(2))
                    seconds = float(match.group(3))

                    current_time = (
                        hours * 3600 +
                        minutes * 60 +
                        seconds
                    )

                    percentage = int(
                        (
                            current_time /
                            total_duration
                        ) * 100
                    )

                    percentage = max(
                        0,
                        min(percentage, 100)
                    )

                    if percentage >= last_percent + 5:

                        last_percent = percentage

                        filled = min(
                            percentage // 10,
                            10
                        )

                        empty = 10 - filled

                        bar = (
                            "▰" * filled +
                            "▱" * empty
                        )

                        await safe_edit_message(
                            status,
                            f"💧 **{label}...**\n\n"
                            f"[{bar}] {percentage}%"
                        )

        await process.wait()

        stderr_text = "".join(stderr_lines)

        if process.returncode != 0:

            print(
                "[FFMPEG FAILED]\n",
                stderr_text[-5000:]
            )

            return False, stderr_text

        print("[FFMPEG] Completed successfully")

        return True, stderr_text

    except asyncio.CancelledError:

        try:
            process.kill()
            await process.wait()
        except Exception:
            pass

        raise

    except Exception as e:

        print(f"[FFMPEG EXCEPTION] {e}")

        return False, str(e)


# ============================================================
# /START
# ============================================================

@app.on_message(filters.command("start"))
async def start_cmd(client, message):

    name = (
        message.from_user.first_name
        if message.from_user
        else "User"
    )

    await message.reply_text(
        f"👋 Hello {name}!\n\n"
        "🤖 **Advanced Media Swiss-Knife Bot**\n\n"
        "Send me a video/file and choose:\n"
        "• 💧 Watermark\n"
        "• 🎵 Stream Tools\n"
        "• 🏷️ Rename\n"
        "• 📦 Zip / Split"
    )


# ============================================================
# MEDIA RECEIVED
# ============================================================

@app.on_message(
    (filters.video | filters.document) &
    filters.private
)
async def handle_media(client, message):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🎬 Stream Tools",
                callback_data="tools_stream"
            ),

            InlineKeyboardButton(
                "🏷️ Rename / Auto-Rename",
                callback_data="tools_rename"
            )
        ],

        [
            InlineKeyboardButton(
                "💧 Watermark Video",
                callback_data="tools_watermark"
            ),

            InlineKeyboardButton(
                "📦 Zip / Split",
                callback_data="tools_zipsplit"
            )
        ]

    ])

    await message.reply_text(
        "⚙️ **Choose the action you want to perform:**",
        reply_markup=keyboard,
        quote=True
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

@app.on_callback_query()
async def callback_handler(client, query):

    data = query.data
    user_id = query.from_user.id

    await query.answer()

    # --------------------------------------------------------
    # Find original media message
    # --------------------------------------------------------

    msg = query.message.reply_to_message

    if not msg:

        await safe_edit_message(
            query.message,
            "❌ **Original file message not found.**\n\n"
            "Please send the file again."
        )

        return

    # ========================================================
    # STREAM TOOLS MENU
    # ========================================================

    if data == "tools_stream":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🎵 Select & Remove Audio",
                    callback_data="select_rm_audio"
                )
            ],

            [
                InlineKeyboardButton(
                    "💬 Select & Remove Subtitle",
                    callback_data="select_rm_sub"
                )
            ],

            [
                InlineKeyboardButton(
                    "❌ Remove ALL Audio",
                    callback_data="rm_all_audio"
                ),

                InlineKeyboardButton(
                    "❌ Remove ALL Subtitle",
                    callback_data="rm_all_sub"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="back_main"
                )
            ]

        ])

        await safe_edit_message(
            query.message,
            "⚙️ **Stream Processing Tools:**",
            keyboard
        )

        return

    # ========================================================
    # WATERMARK MENU
    # ========================================================

    if data == "tools_watermark":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📝 Text Watermark",
                    callback_data="apply_text_watermark"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="back_main"
                )
            ]

        ])

        await safe_edit_message(
            query.message,
            "💧 **Watermark Processor:**",
            keyboard
        )

        return

    # ========================================================
    # APPLY TEXT WATERMARK
    # ========================================================

    if data == "apply_text_watermark":

        status = query.message

        # ----------------------------------------------------
        # Download
        # ----------------------------------------------------

        await safe_edit_message(
            status,
            "📥 **Downloading Video...**"
        )

        file_path = await download_file(
            client,
            msg,
            status,
            "📥 Downloading..."
        )

        if not file_path:
            return

        # Save file path for later operations
        FILE_CACHE[msg.id] = file_path

        # ----------------------------------------------------
        # Watermark settings
        # ----------------------------------------------------

        try:
            wm_text = (
                await db.get_wm_text(user_id)
                or "@Anime_Hub_Tamil"
            )
        except Exception:
            wm_text = "@Anime_Hub_Tamil"

        try:
            wm_pos = (
                await db.get_wm_pos(user_id)
                or "bottom_right"
            )
        except Exception:
            wm_pos = "bottom_right"

        try:
            wm_size = (
                await db.get_wm_size(user_id)
                or "24"
            )
        except Exception:
            wm_size = "24"

        # ----------------------------------------------------
        # Output
        # ----------------------------------------------------

        output_path = str(
            OUTPUT_DIR /
            f"watermarked_{msg.id}_{user_id}.mp4"
        )

        vf_filter = get_drawtext_filter(
            wm_text,
            wm_pos,
            wm_size
        )

        total_duration = await get_video_duration(
            file_path
        )

        await safe_edit_message(
            status,
            "💧 **Starting Watermark...**\n\n"
            "⏳ Please wait..."
        )

        # ----------------------------------------------------
        # FFmpeg
        # ----------------------------------------------------

        ffmpeg_cmd = [

            "ffmpeg",
            "-y",

            "-i",
            file_path,

            "-vf",
            vf_filter,

            # Video
            "-map",
            "0:v:0",

            # Audio if available
            "-map",
            "0:a?",

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "23",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            output_path
        ]

        try:

            success, error_output = await asyncio.wait_for(

                run_ffmpeg(
                    ffmpeg_cmd,
                    status,
                    total_duration,
                    "Watermarking"
                ),

                timeout=FFMPEG_TIMEOUT
            )

        except asyncio.TimeoutError:

            success = False
            error_output = "FFmpeg processing timeout."

        # ----------------------------------------------------
        # Remove source
        # ----------------------------------------------------

        if os.path.exists(file_path):

            try:
                os.remove(file_path)
            except Exception:
                pass

        # ----------------------------------------------------
        # Failed
        # ----------------------------------------------------

        if not success or not os.path.exists(output_path):

            short_error = (
                error_output[-2500:]
                if error_output
                else "Unknown FFmpeg error"
            )

            await safe_edit_message(
                status,
                "❌ **Watermarking Failed!**\n\n"
                f"```text\n{short_error}\n```"
            )

            return

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        output_size = os.path.getsize(
            output_path
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🚀 Direct Upload",
                    callback_data=f"direct_upload|{output_path}"
                )
            ]

        ])

        await safe_edit_message(
            status,
            "✅ **Watermark Added Successfully!**\n\n"
            f"📁 Output Size: "
            f"`{output_size / 1024 / 1024:.2f} MB`\n\n"
            "Ready to upload.",
            keyboard
        )

        return

  # ========================================================
    # DIRECT UPLOAD
    # ========================================================

    if data.startswith("direct_upload|"):

        output_path = data.split(
            "|",
            1
        )[1]

        if not os.path.exists(output_path):

            await safe_edit_message(
                query.message,
                "❌ **Output file not found!**\n\n"
                "Please process the video again."
            )

            return

        status = query.message

        await safe_edit_message(
            status,
            "📤 **Uploading File...**"
        )

        start_time = time.time()

        thumb_path = None

        try:

            # ------------------------------------------------
            # Thumbnail
            # ------------------------------------------------

            thumb_id = await db.get_thumb(
                user_id
            )

            if thumb_id:

                try:

                    thumb_path = await client.download_media(
                        thumb_id,
                        file_name=str(DOWNLOAD_DIR) + "/"
                    )

                except Exception as e:

                    print(
                        f"[THUMB ERROR] {e}"
                    )

# ------------------------------------------------
            # Upload
            # ------------------------------------------------

            await client.send_document(

                chat_id=user_id,

                document=output_path,

                thumb=thumb_path,

                caption=(
                    "✅ **Processed Successfully!**"
                ),

                progress=progress_bar,

                progress_args=(
                    "📤 Uploading File...",
                    start_time,
                    status
                )
            )

            await safe_edit_message(
                status,
                "✅ **Upload Completed!**"
            )

        except Exception as e:

            print(
                f"[UPLOAD ERROR] {repr(e)}"
            )

            await safe_edit_message(
                status,
                "❌ **Upload Failed!**\n\n"
                f"`{str(e)[:1500]}`"
            )

        finally:

            # ------------------------------------------------
            # Cleanup
            # ------------------------------------------------

            if os.path.exists(output_path):

                try:
                    os.remove(output_path)
                except Exception:
                    pass

            if thumb_path and os.path.exists(
                thumb_path
            ):

                try:
                    os.remove(thumb_path)
                except Exception:
                    pass

        return

    # ========================================================
    # SELECT AUDIO / SUBTITLE
    # ========================================================

    if data in (
        "select_rm_audio",
        "select_rm_sub"
    ):

        stream_type = (
            "audio"
            if data == "select_rm_audio"
            else "subtitle"
        )

        await safe_edit_message(
            query.message,
            f"📥 **Downloading video...**\n\n"
            f"Checking {stream_type} streams..."
        )

        file_path = await download_file(
            client,
            msg,
            query.message,
            "📥 Downloading..."
        )

        if not file_path:
            return

        FILE_CACHE[msg.id] = file_path

        streams = await get_file_streams(
            file_path
        )

        target_streams = [

            stream

            for stream in streams

            if stream.get("codec_type") ==
            stream_type
        ]

        if not target_streams:

            if os.path.exists(file_path):
                os.remove(file_path)

            await safe_edit_message(
                query.message,
                f"❌ **No {stream_type} streams found!**"
            )

            return

        buttons = []

        for stream in target_streams:

            index = stream.get(
                "index",
                0
            )

            codec = stream.get(
                "codec_name",
                "unknown"
            )

            language = (
                stream.get(
                    "tags",
                    {}
                ).get(
                    "language",
                    "und"
                )
            )

            buttons.append([

                InlineKeyboardButton(

                    f"🗑️ Stream #{index} "
                    f"[{language.upper()}] "
                    f"({codec})",

                    callback_data=(
                        f"remove_stream|"
                        f"{stream_type}|"
                        f"{index}|"
                        f"{msg.id}"
                    )
                )

            ])

        buttons.append([

            InlineKeyboardButton(
                "🔙 Cancel",
                callback_data="cancel_action"
            )

        ])

        await safe_edit_message(
            query.message,
            f"Choose which **{stream_type.upper()}** "
            f"stream to remove:",
            InlineKeyboardMarkup(buttons)
        )

        return

    # ========================================================
    # REMOVE SELECTED STREAM
    # ========================================================

    if data.startswith("remove_stream|"):

        parts = data.split("|")

        if len(parts) != 4:
            return

        stream_type = parts[1]
        stream_index = parts[2]
        original_msg_id = int(parts[3])

        file_path = FILE_CACHE.get(
            original_msg_id
        )

        if not file_path or not os.path.exists(
            file_path
        ):

            await safe_edit_message(
                query.message,
                "❌ **Source file expired.**\n\n"
                "Please send the video again."
            )

            return

        output_path = str(
            OUTPUT_DIR /
            f"stream_removed_{original_msg_id}.mkv"
        )

        await safe_edit_message(
            query.message,
            f"⚙️ **Removing {stream_type} "
            f"stream #{stream_index}...**"
        )

        command = [

            "ffmpeg",
            "-y",

            "-i",
            file_path,

            "-map",
            "0",

            "-map",
            f"-0:{stream_index}",

            "-c",
            "copy",

            output_path
        ]

        success, error_output = await run_ffmpeg(
            command,
            query.message,
            0,
            "Processing"
        )

        try:
            os.remove(file_path)
        except Exception:
            pass

        FILE_CACHE.pop(
            original_msg_id,
            None
        )

        if not success or not os.path.exists(
            output_path
        ):

            await safe_edit_message(
                query.message,
                "❌ **Stream removal failed!**\n\n"
                f"```text\n"
                f"{error_output[-2000:]}"
                f"\n```"
            )

            return

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🚀 Direct Upload",
                    callback_data=f"direct_upload|{output_path}"
                )
            ]

        ])

        await safe_edit_message(
            query.message,
            f"✅ **Stream #{stream_index} removed!**\n\n"
            "Ready to upload.",
            keyboard
        )

        return

    # ========================================================
    # REMOVE ALL AUDIO
    # ========================================================

    if data == "rm_all_audio":

        await remove_all_streams(
            query,
            msg,
            "audio"
        )

        return

    # ========================================================
    # REMOVE ALL SUBTITLE
    # ========================================================

    if data == "rm_all_sub":

        await remove_all_streams(
            query,
            msg,
            "subtitle"
        )

        return

    # ========================================================
    # BACK
    # ========================================================

    if data == "back_main":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🎬 Stream Tools",
                    callback_data="tools_stream"
                ),

                InlineKeyboardButton(
                    "🏷️ Rename / Auto-Rename",
                    callback_data="tools_rename"
                )
            ],

            [
                InlineKeyboardButton(
                    "💧 Watermark Video",
                    callback_data="tools_watermark"
                ),

                InlineKeyboardButton(
                    "📦 Zip / Split",
                    callback_data="tools_zipsplit"
                )
            ]

        ])

        await safe_edit_message(
            query.message,
            "⚙️ **Choose the action you want to perform:**",
            keyboard
        )

        return

    # ========================================================
    # CANCEL
    # ========================================================

    if data == "cancel_action":

        await safe_edit_message(
            query.message,
            "❌ **Action Cancelled.**"
        )

        return

    # ========================================================
    # UNIMPLEMENTED MENUS
    # ========================================================

    if data in (
        "tools_rename",
        "tools_zipsplit"
    ):

        await safe_edit_message(
            query.message,
            "🚧 **This feature is not enabled "
            "in this version yet.**"
        )

        return


# ============================================================
# REMOVE ALL STREAMS
# ============================================================

async def remove_all_streams(
    query,
    msg,
    stream_type
):

    user_id = query.from_user.id

    await safe_edit_message(
        query.message,
        "📥 **Downloading video...**"
    )

    file_path = await download_file(
        app,
        msg,
        query.message,
        "📥 Downloading..."
    )

    if not file_path:
        return

    stream_output = str(
        OUTPUT_DIR /
        f"no_{stream_type}_{msg.id}.mkv"
    )

    if stream_type == "audio":

        maps = [
            "-map",
            "0",
            "-map",
            "-0:a"
        ]

    else:

        maps = [
            "-map",
            "0",
            "-map",
            "-0:s"
        ]

    command = [

        "ffmpeg",
        "-y",

        "-i",
        file_path,

        *maps,

        "-c",
        "copy",

        stream_output
    ]

    await safe_edit_message(
        query.message,
        f"⚙️ **Removing all {stream_type} streams...**"
    )

    success, error_output = await run_ffmpeg(
        command,
        query.message,
        0,
        "Processing"
    )

    try:
        os.remove(file_path)
    except Exception:
        pass

    if not success or not os.path.exists(
        stream_output
    ):

        await safe_edit_message(
            query.message,
            "❌ **Processing Failed!**\n\n"
            f"```text\n"
            f"{error_output[-2000:]}"
            f"\n```"
        )

        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🚀 Direct Upload",
                callback_data=f"direct_upload|{stream_output}"
            )
        ]

    ])

    await safe_edit_message(
        query.message,
        f"✅ **All {stream_type} streams removed!**",
        keyboard
    )



# ============================================================
# HELP
# ============================================================

@app.on_message(filters.command("help"))
async def help_cmd(client, message):

    await message.reply_text(

        "**Available Commands:**\n\n"

        "/set_thumb - Reply to an image\n"
        "/get_thumb - Get saved thumbnail\n"
        "/del_thumb - Delete thumbnail\n\n"

        "/set_autorename [S01E01]\n"
        "/get_autorename\n"
        "/del_autorename\n\n"

        "/set_wm_text Your Text\n"
        "/del_wm_text\n"

        "/wm_pos bottom_right\n"

        "/wm_size 24\n"
    )


# ============================================================
# THUMBNAIL
# ============================================================

@app.on_message(filters.command("set_thumb"))
async def set_thumb_cmd(client, message):

    if (
        not message.reply_to_message
        or not message.reply_to_message.photo
    ):

        await message.reply_text(
            "⚠️ Reply to a photo with /set_thumb"
        )

        return

    file_id = (
        message.reply_to_message
        .photo
        .file_id
    )

    await db.set_thumb(
        message.from_user.id,
        file_id
    )

    await message.reply_text(
        "✅ **Thumbnail saved!**"
    )


@app.on_message(filters.command("get_thumb"))
async def get_thumb_cmd(client, message):

    thumb_id = await db.get_thumb(
        message.from_user.id
    )

    if not thumb_id:

        await message.reply_text(
            "❌ No thumbnail saved yet."
        )

        return

    await message.reply_photo(
        thumb_id,
        caption="🖼️ Your saved thumbnail"
    )


@app.on_message(filters.command("del_thumb"))
async def del_thumb_cmd(client, message):

    await db.set_thumb(
        message.from_user.id,
        None
    )

    await message.reply_text(
        "🗑️ Thumbnail deleted."
    )

# ============================================================
# AUTO RENAME
# ============================================================

@app.on_message(filters.command("set_autorename"))
async def set_autorename_cmd(client, message):

    if len(message.command) < 2:

        await message.reply_text(
            "⚠️ Usage:\n"
            "`/set_autorename S01E01`"
        )

        return

    pattern = message.text.split(
        None,
        1
    )[1]

    await db.set_auto_rename(
        message.from_user.id,
        pattern
    )

    await message.reply_text(
        f"✅ **Auto-rename pattern set:**\n"
        f"`{pattern}`"
    )


@app.on_message(filters.command("get_autorename"))
async def get_autorename_cmd(client, message):

    pattern = await db.get_auto_rename(
        message.from_user.id
    )

    if not pattern:

        await message.reply_text(
            "❌ No auto-rename pattern set."
        )

        return

    await message.reply_text(
        f"📝 **Current pattern:**\n"
        f"`{pattern}`"
    )


@app.on_message(filters.command("del_autorename"))
async def del_autorename_cmd(client, message):

    await db.set_auto_rename(
        message.from_user.id,
        None
    )

    await message.reply_text(
        "🗑️ Auto-rename pattern cleared."
    )


# ============================================================
# WATERMARK SETTINGS
# ============================================================

@app.on_message(filters.command("set_wm_text"))
async def set_wm_text_cmd(client, message):

    if len(message.command) < 2:

        await message.reply_text(
            "⚠️ Usage:\n"
            "`/set_wm_text Your Text Here`"
        )

        return

    text = message.text.split(
        None,
        1
    )[1]

    await db.set_wm_text(
        message.from_user.id,
        text
    )

    await message.reply_text(
        f"✅ **Watermark text saved:**\n"
        f"`{text}`"
    )


@app.on_message(filters.command("del_wm_text"))
async def del_wm_text_cmd(client, message):

    await db.set_wm_text(
        message.from_user.id,
        None
    )

    await message.reply_text(
        "🗑️ Watermark text reset to default."
    )


@app.on_message(filters.command("wm_pos"))
async def wm_pos_cmd(client, message):

    valid_positions = [
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "center"
    ]

    if (
        len(message.command) < 2
        or message.command[1] not in valid_positions
    ):

        await message.reply_text(

            "⚠️ **Usage:**\n"
            "`/wm_pos bottom_right`\n\n"

            "**Valid:**\n" +
            ", ".join(valid_positions)
        )

        return

    position = message.command[1]

    await db.set_wm_pos(
        message.from_user.id,
        position
    )

    await message.reply_text(
        f"✅ **Watermark position:** `{position}`"
    )


@app.on_message(filters.command("wm_size"))
async def wm_size_cmd(client, message):

    if (
        len(message.command) < 2
        or not message.command[1].isdigit()
    ):

        await message.reply_text(
            "⚠️ Usage:\n"
            "`/wm_size 24`"
        )

        return

    size = int(
        message.command[1]
    )

    if size < 8 or size > 200:

        await message.reply_text(
            "⚠️ Font size must be between 8 and 200."
        )

        return

    await db.set_wm_size(
        message.from_user.id,
        str(size)
    )

    await message.reply_text(
        f"✅ **Watermark size:** `{size}`"
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    print("================================")
    print(" Advanced Media Bot Starting")
    print("================================")

    print(
        "[INFO] FFmpeg:",
        os.system("which ffmpeg")
    )

    print(
        "[INFO] FFprobe:",
        os.system("which ffprobe")
    )

    app.run()
