import motor.motor_asyncio
from config import Config

client = motor.motor_asyncio.AsyncIOMotorClient(Config.MONGO_URL)
db = client["adv_renamer_bot"]
users_col = db["users"]

async def get_user(user_id):
    user = await users_col.find_one({"_id": user_id})
    if not user:
        default_data = {
            "_id": user_id,
            "default_upload": "Telegram",
            "video_tools": True,
            "extra_tools": False,
            "sample_video": False,
            "screenshot": False,
            "wm_position": "bottom_right",
            "wm_size": 25,
            "split_file": False,
            "split_size_mb": 2000,
            "thumbnail": None,
            "metadata_title": "Uploaded By Advance Renamer Bot"
        }
        await users_col.insert_one(default_data)
        return default_data
    return user

async def update_user(user_id, key, value):
    await users_col.update_one({"_id": user_id}, {"$set": {key: value}})

async def reset_user(user_id):
    await users_col.delete_one({"_id": user_id})
    return await get_user(user_id)
  
