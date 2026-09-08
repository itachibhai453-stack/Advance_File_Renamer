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

# ----------------- WATERMARK HELPERS -----------------
def get_drawtext_filter(text, pos="bottom_right", fontsize="24"):
    positions = {
        "top_left": "x=15:y=15",
        "top_right": "x=w-tw-15:y=15",
        "bottom_left": "x=15:y=h-th-15",
        "bottom_right": "x=w-tw-15:y=h-th-15",
        "center": "x=(w-tw)/2:y=(h-th)/2"
    }
    xy = positions.get(pos, positions["bottom_right"])
    return f"drawtext=text='{text}':fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.5:boxborderw=5:{xy}"

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

# ----------------- WATERMARK COMMANDS -----------------
@app.on_message(filters.command("set_wm_text") & filters.private)
async def set_watermark_text(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/set_wm_text @Anime_Hub_Tamil`")
    text = message.text.split(None, 1)[1]
    await db.set_wm_text(message.from_user.id, text)
    await message.reply_text(f"✅ **Watermark Text Saved:** `{text}`")

@app.on_message(filters.command("wm_pos") & filters.private)
async def set_watermark_pos(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/wm_pos [top_left | top_right | bottom_left | bottom_right | center]`")
    pos = message.command[1].lower()
    valid_positions = ["top_left", "top_right", "bottom_left", "bottom_right", "center"]
    if pos not in valid_positions:
        return await message.reply_text("❌ Invalid position! Choose from: `top_left`, `top_right`, `bottom_left`, `bottom_right`, `center`")
    await db.set_wm_pos(message.from_user.id, pos)
    await message.reply_text(f"✅ **Watermark Position set to:** `{pos}`")

@app.on_message(filters.command("wm_size") & filters.private)
async def set_watermark_size(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/wm_size 24` (Font size for text OR % for image)")
    size = message.command[1]
    await db.set_wm_size(message.from_user.id, size)
    await message.reply_text(f"✅ **Watermark Size set to:** `{size}`")

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

    elif data == "ext_audio":
        status = await query.message.edit_text("📥 Downloading video to extract audio...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        output_path = f"audio_{msg.id}.mp3"
        cmd = f'ffmpeg -i "{file_path}" -vn -acodec libmp3lame -q:a 2 "{output_path}" -y'
        
        await status.edit_text("🎵 Extracting Audio Stream...")
        subprocess.run(cmd, shell=True)

        os.remove(file_path)
        await status.edit_text("📤 Uploading Extracted Audio...")
        await client.send_document(chat_id=user_id, document=output_path)
        if os.path.exists(output_path): os.remove(output_path)
        await status.delete()

    elif data == "ext_sub":
        status = await query.message.edit_text("📥 Downloading video to extract subtitles...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        output_path = f"subtitle_{msg.id}.srt"
        cmd = f'ffmpeg -i "{file_path}" -map 0:s:0 "{output_path}" -y'
        
        await status.edit_text("💬 Extracting Subtitle Stream...")
        subprocess.run(cmd, shell=True)

        os.remove(file_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await status.edit_text("📤 Uploading Extracted Subtitle...")
            await client.send_document(chat_id=user_id, document=output_path)
            os.remove(output_path)
            await status.delete()
        else:
            await status.edit_text("❌ No valid subtitle stream found in this video!")

    elif data == "rm_audio":
        status = await query.message.edit_text("📥 Downloading file for processing...")
        start_time = time.time()
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        output_path = f"no_audio_{msg.id}.mp4"
        cmd = f'ffmpeg -i "{file_path}" -an -c:v copy "{output_path}" -y'
        
        await status.edit_text("⚙️ Removing Audio Streams...")
        subprocess.run(cmd, shell=True)

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

    elif data == "tools_watermark":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Text Watermark", callback_data="apply_text_watermark")],
            [InlineKeyboardButton("⚙️ Watermark Settings", callback_data="wm_settings_info")]
        ])
        await query.message.edit_text("💧 **Watermark Processor:**\nSelect watermark type to apply:", reply_markup=kb)

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
        file_path = await client.download_media(msg, progress=progress_bar, progress_args=("📥 Downloading...", start_time, status))
        
        wm_text = await db.get_wm_text(user_id) or "@Anime_Hub_Tamil"
        wm_pos = await db.get_wm_pos(user_id) or "bottom_right"
        wm_size = await db.get_wm_size(user_id) or "24"

        output_path = f"wm_{msg.id}.mp4"
        vf_filter = get_drawtext_filter(wm_text, wm_pos, wm_size)
        
        cmd = f'ffmpeg -i "{file_path}" -vf "{vf_filter}" -c:a copy "{output_path}" -y'
        
        await status.edit_text("💧 Adding Text Watermark to Video...")
        subprocess.run(cmd, shell=True)

        os.remove(file_path)
        await status.edit_text("✅ Watermark Added Successfully!\n\n**Select next action:**", 
                               reply_markup=InlineKeyboardMarkup([
                                   [InlineKeyboardButton("✏️ Custom Rename", callback_data=f"do_rename_{output_path}"),
                                    InlineKeyboardButton("🤖 Auto Rename", callback_data=f"do_autorename_{output_path}")],
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
        
        if os.path.exists(output_path): os.remove(output_path)
        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
        await status.delete()

    elif data == "tools_zipsplit":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Zip Extract", callback_data="do_zipextract")]
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

        os.remove(file_path)
        import shutil
        shutil.rmtree(extract_dir)
        await status.edit_text("✅ Extraction and Upload Completed!")

if __name__ == "__main__":
    app.run()
      
