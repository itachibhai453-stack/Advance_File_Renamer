import os
import time
import math
import shutil
import json
import zipfile
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from config import Config
from database import get_user, update_user, reset_user

app = Client(
    "AdvFileRenamerBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

USER_STATE = {}
CANCEL_TASKS = set()

# ----------------- PROGRESS BAR -----------------
def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

async def progress_bar(current, total, status_msg, start_time, action_name, user_id):
    if user_id in CANCEL_TASKS:
        raise asyncio.CancelledError("Operation Cancelled by User.")

    now = time.time()
    diff = now - start_time
    if round(diff % 4) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        time_to_completion = round((total - current) / speed) if speed > 0 else 0

        progress = "".join(["■" for _ in range(math.floor(percentage / 10))]) + \
                   "".join(["□" for _ in range(10 - math.floor(percentage / 10))])

        tmp = (
            f"**{action_name}...**\n\n"
            f"[{progress}] {percentage:.2f}%\n"
            f"**Processed:** {humanbytes(current)} / {humanbytes(total)}\n"
            f"**Speed:** {humanbytes(speed)}/s | **ETA:** {time_to_completion}s\n\n"
            f"🚫 Send /cancel to stop this task."
        )
        try:
            await status_msg.edit_text(tmp)
        except Exception:
            pass

# ----------------- SETTINGS MENU -----------------
async def build_settings_keyboard(user_id):
    s = await get_user(user_id)
    
    upload_text = f"Default Upload | {s.get('default_upload', 'Telegram')}"
    video_tools_text = f"📹 Video Tools {'✅' if s.get('video_tools', True) else '❌'}"
    extra_tools_text = f"🛠 Extra Tools {'✅' if s.get('extra_tools', True) else '❌'}"
    sample_text = f"🎞 Sample Video {'✅' if s.get('sample_video', False) else '❌'}"
    ss_text = f"📸 Screenshot {'✅' if s.get('screenshot', False) else '❌'}"

    keyboard = [
        [InlineKeyboardButton(upload_text, callback_data="toggle_upload")],
        [
            InlineKeyboardButton("📺 TG Tools", callback_data="tool_tg"),
            InlineKeyboardButton("📂 GoFile Tools", callback_data="tool_gofile")
        ],
        [InlineKeyboardButton("🤖 Bots for Upload", callback_data="tool_bots")],
        [
            InlineKeyboardButton(extra_tools_text, callback_data="toggle_extra"),
            InlineKeyboardButton(video_tools_text, callback_data="toggle_video")
        ],
        [
            InlineKeyboardButton(sample_text, callback_data="toggle_sample"),
            InlineKeyboardButton(ss_text, callback_data="toggle_ss")
        ],
        [
            InlineKeyboardButton("🔄 Reset All", callback_data="reset_settings"),
            InlineKeyboardButton("❌ Close", callback_data="close_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    user_id = message.from_user.id
    USER_STATE.pop(user_id, None)
    await get_user(user_id)
    text = (
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        f"I am an **Advance File Renamer Bot**.\n\n"
        f"📌 **Commands:**\n"
        f"• `/setmetadata <text>` - Set custom video metadata title\n"
        f"• Send Photo with caption `/setwatermark` - Set Watermark logo\n"
        f"• `/setsplit <MB>` - Set auto-split chunk size (Default 1900MB)\n"
        f"• `/cancel` - Cancel ongoing task\n"
        f"• `/settings` - Open Settings"
    )
    await message.reply_text(text)

@app.on_message(filters.command("settings") & filters.private)
async def settings_command(client, message: Message):
    user_id = message.from_user.id
    USER_STATE.pop(user_id, None)
    settings = await get_user(user_id)
    text = f"**Settings Panel for {message.from_user.first_name}**\n\nDefault Upload Target: **{settings.get('default_upload', 'Telegram')}**"
    await message.reply_text(text, reply_markup=await build_settings_keyboard(user_id))

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id
    s = await get_user(user_id)

    if data == "toggle_upload":
        new_val = "GoFile" if s.get("default_upload") == "Telegram" else "Telegram"
        await update_user(user_id, "default_upload", new_val)
    elif data == "toggle_video":
        await update_user(user_id, "video_tools", not s.get("video_tools", True))
    elif data == "toggle_extra":
        await update_user(user_id, "extra_tools", not s.get("extra_tools", True))
    elif data == "toggle_sample":
        await update_user(user_id, "sample_video", not s.get("sample_video", False))
    elif data == "toggle_ss":
        await update_user(user_id, "screenshot", not s.get("screenshot", False))
    elif data == "reset_settings":
        await reset_user(user_id)
        await query.answer("Settings Reset!", show_alert=True)
    elif data == "close_menu":
        await query.message.delete()
        return

    s = await get_user(user_id)
    text = f"**Settings Panel for {query.from_user.first_name}**\n\nDefault Upload Target: **{s.get('default_upload', 'Telegram')}**"
    await query.message.edit_text(text, reply_markup=await build_settings_keyboard(user_id))

# ----------------- COMMANDS -----------------
@app.on_message(filters.command("cancel") & filters.private)
async def cancel_handler(client, message: Message):
    user_id = message.from_user.id
    CANCEL_TASKS.add(user_id)
    USER_STATE.pop(user_id, None)
    user_dir = os.path.join(Config.DOWNLOAD_DIR, str(user_id))
    shutil.rmtree(user_dir, ignore_errors=True)
    await message.reply_text("🛑 **Process Cancelled & Cleaned up!**")

@app.on_message(filters.command("setmetadata") & filters.private)
async def set_metadata_handler(client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/setmetadata Custom Title`")
    title = message.text.split(" ", 1)[1]
    await update_user(user_id, "metadata_title", title)
    await message.reply_text(f"✅ **Metadata Title Saved:** `{title}`")

@app.on_message(filters.command("setsplit") & filters.private)
async def set_split_handler(client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/setsplit 1900` (in MB)")
    try:
        size_mb = int(message.command[1])
        await update_user(user_id, "split_size_mb", size_mb)
        await message.reply_text(f"✅ **Split Limit Set to:** `{size_mb} MB`")
    except ValueError:
        await message.reply_text("❌ Enter a valid number.")

@app.on_message(filters.photo & filters.private)
async def photo_or_watermark_handler(client, message: Message):
    user_id = message.from_user.id
    user_dir = os.path.join(Config.DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)

    if message.caption and "/setwatermark" in message.caption:
        wm_path = os.path.join(user_dir, "watermark.png")
        await message.download(file_name=wm_path)
        await update_user(user_id, "watermark_img", wm_path)
        await message.reply_text("✅ **Watermark Image Saved Successfully!**")
    else:
        thumb_path = os.path.join(user_dir, "thumb.jpg")
        await message.download(file_name=thumb_path)
        await update_user(user_id, "thumbnail", thumb_path)
        await message.reply_text("🖼️ **Custom Thumbnail Saved!**")

# ----------------- FFPROBE & STREAM SELECTOR -----------------
async def run_shell_command(cmd):
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    return stdout.decode('utf-8', errors='ignore')

async def get_video_streams(file_path):
    cmd = f'ffprobe -v quiet -print_format json -show_streams "{file_path}"'
    res = await run_shell_command(cmd)
    try:
        data = json.loads(res)
        return data.get("streams", [])
    except Exception:
        return []

async def build_stream_keyboard(streams, selected_indices):
    keyboard = []
    for idx, st in enumerate(streams):
        s_type = st.get("codec_type", "unknown").upper()
        s_lang = st.get("tags", {}).get("language", "und")
        s_title = st.get("tags", {}).get("title", s_type)
        
        is_selected = "✅" if idx in selected_indices else "❌"
        btn_text = f"{is_selected} [{idx}] {s_type} ({s_lang}) - {s_title[:15]}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"str_toggle_{idx}")])
    
    keyboard.append([InlineKeyboardButton("🚀 Process Selected Streams", callback_data="str_done")])
    return InlineKeyboardMarkup(keyboard)

# ----------------- MAIN DOWNLOAD & PROCESS -----------------
@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def process_incoming_file(client, message: Message):
    user_id = message.from_user.id
    if user_id in CANCEL_TASKS:
        CANCEL_TASKS.remove(user_id)
        
    s = await get_user(user_id)
    user_dir = os.path.join(Config.DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    
    status_msg = await message.reply_text("📥 **Downloading File...**")
    start_time = time.time()

    try:
        file_path = await message.download(
            file_name=os.path.join(user_dir, ""),
            progress=progress_bar,
            progress_args=(status_msg, start_time, "📥 Downloading File", user_id)
        )
    except asyncio.CancelledError:
        return

    processed_files = []

    # 1. ZIP Handling
    if file_path.endswith(".zip"):
        await status_msg.edit_text("📦 **Extracting ZIP File...**")
        extract_folder = os.path.join(user_dir, "extracted")
        os.makedirs(extract_folder, exist_ok=True)
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        
        for root, _, files in os.walk(extract_folder):
            for f in files:
                processed_files.append(os.path.join(root, f))
    else:
        processed_files.append(file_path)

    cur_file = processed_files[0]
    is_video = cur_file.endswith(".mp4") or cur_file.endswith(".mkv")

    # 2. Video Stream Scan
    if s.get("video_tools", True) and is_video:
        await status_msg.edit_text("🔍 **Scanning Video Streams...**")
        streams = await get_video_streams(cur_file)
        
        if streams:
            default_selected = [i for i, st in enumerate(streams) if st.get("codec_type") in ["video", "audio"]]
            USER_STATE[user_id] = {
                "action": "selecting_streams",
                "file_path": cur_file,
                "streams": streams,
                "selected_indices": set(default_selected),
                "status_msg_id": status_msg.id,
                "user_dir": user_dir,
                "all_files": processed_files
            }

            reply_kb = await build_stream_keyboard(streams, default_selected)
            await status_msg.edit_text(
                "🎬 **Select/Deselect Streams to KEEP:**\n"
                "(Unselected streams will be removed)",
                reply_markup=reply_kb
            )
            return

    # Non-video fallback
    USER_STATE[user_id] = {
        "action": "awaiting_rename",
        "file_list": processed_files,
        "status_msg_id": status_msg.id,
        "user_dir": user_dir
    }
    
    orig_name = os.path.basename(cur_file)
    await status_msg.edit_text(
        f"✨ **File Ready:** `{orig_name}`\n\n"
        f"✏️ **Please send the NEW RENAME FILE NAME now:**"
    )

# ----------------- STREAM REMOVER CALLBACK -----------------
@app.on_callback_query(filters.regex(r"^str_"))
async def stream_selection_callback(client, query: CallbackQuery):
    user_id = query.from_user.id
    state = USER_STATE.get(user_id)

    if not state or state.get("action") != "selecting_streams":
        return await query.answer("Session expired!", show_alert=True)

    data = query.data
    streams = state["streams"]
    selected = state["selected_indices"]
    cur_file = state["file_path"]

    if data.startswith("str_toggle_"):
        idx = int(data.split("_")[2])
        if idx in selected:
            selected.remove(idx)
        else:
            selected.add(idx)
        
        reply_kb = await build_stream_keyboard(streams, selected)
        await query.message.edit_reply_markup(reply_markup=reply_kb)
        await query.answer()

    elif data == "str_done":
        await query.message.edit_text("⚙️ **Filtering Streams, Watermarking & Processing...**")
        s = await get_user(user_id)
        
        base = os.path.splitext(cur_file)[0]
        out_v = f"{base}_proc.mkv"
        
        map_cmd = "".join([f" -map 0:{idx}" for idx in sorted(list(selected))])
        wm_path = s.get("watermark_img")
        metadata_title = s.get("metadata_title", "Uploaded By Adv Renamer")

        # FIXED FFMPEG ENCODING COMMAND FOR WATERMARK & STREAMS
        if wm_path and os.path.exists(wm_path):
            wm_pos = s.get("wm_position", "bottom_right")
            pos_map = {
                "top_left": "10:10",
                "top_right": "main_w-overlay_w-10:10",
                "bottom_left": "10:main_h-overlay_h-10",
                "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10"
            }
            overlay = pos_map.get(wm_pos, "main_w-overlay_w-10:main_h-overlay_h-10")
            cmd = (
                f'ffmpeg -i "{cur_file}" -i "{wm_path}" '
                f'-filter_complex "[1:v]scale=iw*{s.get("wm_size", 25)}/100:-1[wm];[0:v][wm]overlay={overlay}[v]" '
                f'-map "[v]"{map_cmd} -c:v libx264 -preset superfast -c:a copy -metadata title="{metadata_title}" "{out_v}" -y'
            )
        else:
            cmd = f'ffmpeg -i "{cur_file}"{map_cmd} -c copy -metadata title="{metadata_title}" "{out_v}" -y'

        await run_shell_command(cmd)
        final_file = out_v if os.path.exists(out_v) else cur_file
        
        USER_STATE[user_id] = {
            "action": "awaiting_rename",
            "file_list": [final_file],
            "status_msg_id": query.message.id,
            "user_dir": state["user_dir"]
        }

        orig_name = os.path.basename(final_file)
        await query.message.edit_text(
            f"✨ **Streams Filtered & Watermarked Successfully!**\n\n"
            f"✏️ **Please send the NEW RENAME FILE NAME now:**"
        )

# ----------------- RENAME & UPLOAD -----------------
@app.on_message(filters.text & filters.private & ~filters.command(["start", "settings", "cancel", "setmetadata", "setsplit"]))
async def handle_rename_input(client, message: Message):
    user_id = message.from_user.id
    if user_id not in USER_STATE or USER_STATE[user_id].get("action") != "awaiting_rename":
        return

    state_data = USER_STATE.pop(user_id)
    new_name = message.text.strip()
    files = state_data["file_list"]
    user_dir = state_data["user_dir"]
    s = await get_user(user_id)

    status_msg = await message.reply_text("🔄 **Renaming File...**")

    upload_queue = []
    for cur_file in files:
        ext = os.path.splitext(cur_file)[1]
        final_name = new_name if new_name.endswith(ext) else new_name + ext
        target_path = os.path.join(os.path.dirname(cur_file), final_name)
        os.rename(cur_file, target_path)
        upload_queue.append(target_path)

    # Split Check
    final_upload_list = []
    split_size = s.get("split_size_mb", 1900) * 1024 * 1024
    
    for f in upload_queue:
        if os.path.getsize(f) > split_size:
            await status_msg.edit_text("✂️ **Splitting Large File...**")
            part_num = 1
            with open(f, 'rb') as src:
                while True:
                    chunk = src.read(split_size)
                    if not chunk:
                        break
                    p_name = f"{f}.part{part_num:03d}"
                    with open(p_name, 'wb') as dest:
                        dest.write(chunk)
                    final_upload_list.append(p_name)
                    part_num += 1
        else:
            final_upload_list.append(f)

    # Upload
    for up_file in final_upload_list:
        if user_id in CANCEL_TASKS:
            break
        up_start = time.time()
        file_title = os.path.basename(up_file)
        thumb = s.get("thumbnail") if (s.get("thumbnail") and os.path.exists(s.get("thumbnail"))) else None
        
        try:
            await client.send_document(
                chat_id=message.chat.id,
                document=up_file,
                thumb=thumb,
                caption=f"✅ **Processed File:** `{file_title}`",
                progress=progress_bar,
                progress_args=(status_msg, up_start, f"📤 Uploading {file_title}", user_id)
            )
        except asyncio.CancelledError:
            break

    shutil.rmtree(user_dir, ignore_errors=True)
    await status_msg.delete()

# ----------------- MAIN RUNNER -----------------
async def main():
    print("Bot is starting...")
    await app.start()
    print("Bot Started Successfully!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
        
