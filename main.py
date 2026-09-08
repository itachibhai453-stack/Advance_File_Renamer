import os
import time
import math
import asyncio
import zipfile
import subprocess
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from config import Config
from database import db

app = Client("MediaAdvancedBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN)

# ----------------- PROGRESS BAR UTILITY -----------------
async def progress_bar(current, total, status_text, start_time, message):
    now = time.time()
    diff = now - start_time
    if round(diff % 5) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        elapsed_time = round(diff)
        time_to_completion = round((total - current) / speed) if speed > 0 else 0
        
        progress = "[{0}{1}] {2}%\n".format(
            ''.join(["▰" for _ in range(math.floor(percentage / 10))]),
            ''.join(["▱" for _ in range(10 - math.floor(percentage / 10))]),
            round(percentage, 2)
        )
        
        tmp = progress + f"**Speed:** {round(speed / 1024 / 1024, 2)} MB/s\n" + \
              f"**Done:** {round(current / 1024 / 1024, 2)} MB / {round(total / 1024 / 1024, 2)} MB\n" + \
              f"**ETA:** {time_to_completion}s"
        
        try:
            await message.edit_text(f"**{status_text}**\n\n{tmp}")
        except:
            pass

# ----------------- WATERMARK HELPER -----------------
def get_wm_overlay_position(position, size_percent):
    scale_filter = f"scale=iw*{size_percent}/100:-1"
    positions = {
        "top_left": "overlay=10:10",
        "top_right": "overlay=main_w-overlay_w-10:10",
        "bottom_left": "overlay=10:main_h-overlay_h-10",
        "bottom_right": "overlay=main_w-overlay_w-10:main_h-overlay_h-10",
        "center": "overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    }
    return scale_filter, positions.get(position, positions["bottom_right"])

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
        await message.reply_text("⚠️ Reply to an image with `/set_thumb` to save it.")

@app.on_message(filters.command("set_autorename") & filters.private)
async def set_auto_rename_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: `/set_autorename [Episode_{ep}_1080p]`")
    pattern = message.text.split(None, 1)[1]
    await db.set_auto_rename(message.from_user.id, pattern)
    await message.reply_text(f"✅ Auto-Rename Pattern set to: `{pattern}`")

# ----------------- MEDIA PROCESSOR -----------------
@app.on_message((filters.video | filters.document) & filters.private)
async def handle_media(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Stream Tools", callback_data="tools_stream"), InlineKeyboardButton("🏷️ Rename / Auto-Rename", callback_data="tools_rename")],
        [InlineKeyboardButton("💧 Watermark Video", callback_data="tools_watermark"), InlineKeyboardButton("📦 Zip / Split", callback_data="tools_zipsplit")],
        [InlineKeyboardButton("📝 Edit Metadata", callback_data="tools_metadata")]
    ])
    await message.reply_text("⚙️ **Choose the action you want to perform:**", reply_markup=keyboard, quote=True)

# ----------------- CALLBACK BUTTONS -----------------
@app.on_callback_query()
async def cb_handler(client, query):
    data = query.data
    user_id = query.from_user.id
    msg = query.message.reply_to_message

    if data == "tools_stream":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Extract Audio", callback_data="ext_audio"), InlineKeyboardButton("💬 Extract Subtitle", callback_data="ext_sub")],
            [InlineKeyboardButton("❌ Remove Audio", callback_data="rm_audio"), InlineKeyboardButton("❌ Remove Subtitle", callback_data="rm_sub")],
            [InlineKeyboardButton("➕ Add External Audio", callback_data="add_audio")]
        ])
        await query.message.edit_text("⚙️ **Stream Processing Tools:**", reply_markup=kb)

    elif data == "rm_audio":
        status = await query.message.edit_text("📥 Downloading file for processing...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        output_path = f"no_audio_{msg.id}.mp4"
        cmd = f'ffmpeg -i "{file_path}" -an -c:v copy "{output_path}" -y'
        
        await status.edit_text("⚙️ Removing Audio Streams...")
        subprocess.run(cmd, shell=True)

        # Post-Processing Workflow: Trigger Rename Option
        os.remove(file_path)
        await status.edit_text("✅ Audio removed successfully!\n\n**Do you want to rename this file before upload?**", 
                               reply_markup=InlineKeyboardMarkup([
                                   [InlineKeyboardButton("✏️ Custom Rename", callback_data=f"do_rename_{output_path}"),
                                    InlineKeyboardButton("🤖 Apply Auto-Rename", callback_data=f"do_autorename_{output_path}")],
                                   [InlineKeyboardButton("🚀 Direct Upload", callback_data=f"direct_upload_{output_path}")]
                               ]))

    elif data == "rm_sub":
        status = await query.message.edit_text("📥 Downloading file...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        output_path = f"no_sub_{msg.id}.mp4"
        cmd = f'ffmpeg -i "{file_path}" -sn -c:v copy -c:a copy "{output_path}" -y'
        
        await status.edit_text("⚙️ Removing Subtitle Streams...")
        subprocess.run(cmd, shell=True)

        os.remove(file_path)
        await status.edit_text("✅ Subtitles removed successfully!\n\n**Select next action:**", 
                               reply_markup=InlineKeyboardMarkup([
                                   [InlineKeyboardButton("✏️ Custom Rename", callback_data=f"do_rename_{output_path}"),
                                    InlineKeyboardButton("🤖 Apply Auto-Rename", callback_data=f"do_autorename_{output_path}")],
                                   [InlineKeyboardButton("🚀 Direct Upload", callback_data=f"direct_upload_{output_path}")]
                               ]))

    elif data.startswith("direct_upload_"):
        output_path = data.split("_", 2)[2]
        status = await query.message.edit_text("📤 Uploading file...")
        start_time = time.time()
        
        thumb_id = await db.get_thumb(user_id)
        thumb_path = await client.download_media(thumb_id) if thumb_id else None

        await client.send_document(
            chat_id=user_id,
            document=output_path,
            thumb=thumb_path,
            progress=progress_bar,
            progress_args=("📤 Uploading...", start_time, status)
        )
        
        # Cleanup
        if os.path.exists(output_path): os.remove(output_path)
        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
        await status.delete()

    elif data == "tools_watermark":
        await query.message.edit_text(
            "💧 **Watermark Settings:**\n"
            "Send watermark image first using `/set_wm_img` (Reply to image)\n"
            "Set Direction: `/wm_pos [bottom_right | top_left | center]`\n"
            "Set Size: `/wm_size 15` (Percent scale)"
        )

    elif data == "tools_zipsplit":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Zip Extract", callback_data="do_zipextract")],
            [InlineKeyboardButton("✂️ Split Video (Parts)", callback_data="do_filesplit")]
        ])
        await query.message.edit_text("📦 **Zip & Split Options:**", reply_markup=kb)

    elif data == "do_zipextract":
        status = await query.message.edit_text("📥 Downloading ZIP archive...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading ZIP...", start_time, status))

        extract_dir = f"extracted_{msg.id}"
        os.makedirs(extract_dir, exist_ok=True)

        await status.edit_text("📦 Extracting Files...")
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        await status.edit_text("📤 Uploading Extracted Contents...")
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                f_path = os.path.join(root, f)
                await client.send_document(user_id, document=f_path)

        # Cleanup
        os.remove(file_path)
        import shutil
        shutil.rmtree(extract_dir)
        await status.edit_text("✅ Extraction and Upload Completed!")

if __name__ == "__main__":
    app.run()
        
