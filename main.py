import os
import time
import math
import shutil
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

# Global State Tracker for User Inputs (Rename Name & Settings state)
USER_STATE = {}

# ----------------- PROGRESS BAR HELPER -----------------
def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

async def progress_bar(current, total, status_msg, start_time, action_name):
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
            f"**Speed:** {humanbytes(speed)}/s | **ETA:** {time_to_completion}s"
        )
        try:
            await status_msg.edit_text(tmp)
        except Exception:
            pass


# ----------------- SETTINGS UI MENU -----------------
async def build_settings_keyboard(user_id):
    s = await get_user(user_id)
    
    upload_text = f"Default Upload | {s.get('default_upload', 'Telegram')}"
    video_tools_text = f"📹 Video Tools {'✅' if s.get('video_tools', True) else '❌'}"
    extra_tools_text = f"🛠 Extra Tools {'✅' if s.get('extra_tools', False) else '❌'}"
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
    USER_STATE.pop(user_id, None) # Reset State
    await get_user(user_id)
    text = (
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        f"I am an **Advance File Renamer Bot**.\n\n"
        f"➡️ **Send me any File, Video, or Audio to rename!**\n"
        f"🖼️ **Send a Photo to set a Custom Thumbnail.**\n"
        f"⚙️ **Use /settings to configure your preferences.**"
    )
    await message.reply_text(text)

@app.on_message(filters.command("settings") & filters.private)
async def settings_command(client, message: Message):
    user_id = message.from_user.id
    USER_STATE.pop(user_id, None) # Reset State
    settings = await get_user(user_id)
    text = f"**Settings for {message.from_user.first_name}**\n\nDefault Upload is **{settings.get('default_upload', 'Telegram')}**"
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
        await update_user(user_id, "extra_tools", not s.get("extra_tools", False))
    elif data == "toggle_sample":
        await update_user(user_id, "sample_video", not s.get("sample_video", False))
    elif data == "toggle_ss":
        await update_user(user_id, "screenshot", not s.get("screenshot", False))
    elif data == "reset_settings":
        await reset_user(user_id)
    elif data == "close_menu":
        await query.message.delete()
        return

    s = await get_user(user_id)
    text = f"**Settings for {query.from_user.first_name}**\n\nDefault Upload is **{s.get('default_upload', 'Telegram')}**"
    await query.message.edit_text(text, reply_markup=await build_settings_keyboard(user_id))


# ----------------- THUMBNAIL HANDLER -----------------
@app.on_message(filters.photo & filters.private)
async def set_thumbnail(client, message: Message):
    user_id = message.from_user.id
    user_dir = os.path.join(Config.DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    
    thumb_path = os.path.join(user_dir, "thumb.jpg")
    await message.download(file_name=thumb_path)
    await update_user(user_id, "thumbnail", thumb_path)
    await message.reply_text("✅ **Custom Thumbnail Saved Successfully in Database!**")


# ----------------- FFMPEG ENGINE -----------------
async def run_shell_command(cmd):
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()

async def ffmpeg_apply_metadata_and_watermark(video_file, output_file, metadata_title, wm_image_path=None, position="bottom_right", size_pct=25):
    pos_map = {
        "top_left": "10:10",
        "top_right": "main_w-overlay_w-10:10",
        "bottom_left": "10:main_h-overlay_h-10",
        "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10"
    }
    overlay = pos_map.get(position, "main_w-overlay_w-10:main_h-overlay_h-10")

    if wm_image_path and os.path.exists(wm_image_path):
        cmd = (
            f'ffmpeg -i "{video_file}" -i "{wm_image_path}" '
            f'-filter_complex "[1:v]scale=iw*{size_pct}/100:-1[wm];[0:v][wm]overlay={overlay}" '
            f'-metadata title="{metadata_title}" -c:a copy "{output_file}" -y'
        )
    else:
        cmd = f'ffmpeg -i "{video_file}" -metadata title="{metadata_title}" -c copy "{output_file}" -y'

    await run_shell_command(cmd)


# ----------------- STEP 1: MAIN FILE RECEIVER -----------------
@app.on_message((filters.document | filters.video | filters.audio) & filters.private)
async def process_incoming_file(client, message: Message):
    user_id = message.from_user.id
    s = await get_user(user_id)
    
    user_dir = os.path.join(Config.DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    
    status_msg = await message.reply_text("📥 **Starting Download...**")
    start_time = time.time()

    # 1. Download File
    file_path = await message.download(
        file_name=os.path.join(user_dir, ""),
        progress=progress_bar,
        progress_args=(status_msg, start_time, "📥 Downloading File")
    )

    processed_files = [file_path]

    # 2. ZIP Extraction Option
    if s.get("extra_tools") and file_path.endswith(".zip"):
        await status_msg.edit_text("📦 **Extracting ZIP File...**")
        extract_folder = os.path.join(user_dir, "extracted")
        os.makedirs(extract_folder, exist_ok=True)
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
        
        extracted_list = []
        for root, _, files in os.walk(extract_folder):
            for file in files:
                extracted_list.append(os.path.join(root, file))
        if extracted_list:
            processed_files = extracted_list

    # 3. Stream & Video Operations (Metadata & Watermark)
    final_ready_files = []
    for cur_file in processed_files:
        if s.get("video_tools", True) and (cur_file.endswith(".mp4") or cur_file.endswith(".mkv")):
            await status_msg.edit_text("⚙️ **Applying Metadata & Watermark...**")
            
            # Clean filename extension duplication
            base_name = os.path.splitext(cur_file)[0]
            out_v = f"{base_name}_mod.mkv"
            wm_file = "watermark.png"
            
            await ffmpeg_apply_metadata_and_watermark(
                cur_file, out_v, s.get("metadata_title", "Uploaded By Adv Renamer"),
                wm_image_path=wm_file if os.path.exists(wm_file) else None,
                position=s.get("wm_position", "bottom_right"), 
                size_pct=s.get("wm_size", 25)
            )
            
            if os.path.exists(out_v):
                final_ready_files.append(out_v)
            else:
                final_ready_files.append(cur_file)
        else:
            final_ready_files.append(cur_file)

    # Store state for User Input (Text Rename Prompt)
    USER_STATE[user_id] = {
        "action": "awaiting_rename",
        "file_list": final_ready_files,
        "status_msg_id": status_msg.id,
        "user_dir": user_dir
    }

    orig_name = os.path.basename(final_ready_files[0])
    await status_msg.edit_text(
        f"✨ **Work Finished for:** `{orig_name}`\n\n"
        f"✏️ **Please send the NEW RENAME FILE NAME now:**"
    )


# ----------------- STEP 2: RENAME TEXT CATCHER & UPLOADER -----------------
@app.on_message(filters.text & filters.private & ~filters.command(["start", "settings"]))
async def handle_rename_input(client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in USER_STATE or USER_STATE[user_id].get("action") != "awaiting_rename":
        return # Normal text message, ignore or reply

    state_data = USER_STATE.pop(user_id)
    new_name = message.text.strip()
    files = state_data["file_list"]
    user_dir = state_data["user_dir"]
    s = await get_user(user_id)

    status_msg = await message.reply_text("🔄 **Renaming & Preparing Upload...**")

    upload_queue = []
    for cur_file in files:
        # Check Extension
        ext = os.path.splitext(cur_file)[1]
        if not new_name.endswith(ext) and ext != "":
            final_name = new_name + ext
        else:
            final_name = new_name

        target_path = os.path.join(os.path.dirname(cur_file), final_name)
        os.rename(cur_file, target_path)
        upload_queue.append(target_path)

    # Upload Files
    for up_file in upload_queue:
        up_start = time.time()
        file_title = os.path.basename(up_file)
        thumb = s.get("thumbnail") if (s.get("thumbnail") and os.path.exists(s.get("thumbnail"))) else None
        
        await client.send_document(
            chat_id=message.chat.id,
            document=up_file,
            thumb=thumb,
            caption=f"✅ **Processed File:** `{file_title}`",
            progress=progress_bar,
            progress_args=(status_msg, up_start, f"📤 Uploading {file_title}")
        )

    shutil.rmtree(user_dir, ignore_errors=True)
    await status_msg.delete()


# ----------------- MAIN RUNNER WITH ASYNC LOOP -----------------
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
    
