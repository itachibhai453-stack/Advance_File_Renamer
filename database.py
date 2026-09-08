import motor.motor_asyncio
from config import Config

class Database:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(Config.DB_URL)
        self.db = self.client[Config.DB_NAME]
        self.users = self.db.users

    async def set_thumb(self, user_id, file_id):
        await self.users.update_one({"_id": user_id}, {"$set": {"thumb": file_id}}, upsert=True)

    async def get_thumb(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("thumb") if user else None

    async def set_auto_rename(self, user_id, pattern):
        await self.users.update_one({"_id": user_id}, {"$set": {"auto_rename": pattern}}, upsert=True)

    async def get_auto_rename(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("auto_rename") if user else None

    async def set_metadata(self, user_id, title):
        await self.users.update_one({"_id": user_id}, {"$set": {"metadata": title}}, upsert=True)

    async def get_metadata(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("metadata") if user else None

    # Text Watermark database options
    async def set_wm_text(self, user_id, text):
        await self.users.update_one({"_id": user_id}, {"$set": {"wm_text": text}}, upsert=True)

    async def get_wm_text(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("wm_text") if user else None

    async def set_wm_pos(self, user_id, pos):
        await self.users.update_one({"_id": user_id}, {"$set": {"wm_pos": pos}}, upsert=True)

    async def get_wm_pos(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("wm_pos") if user else "bottom_right"

    async def set_wm_size(self, user_id, size):
        await self.users.update_one({"_id": user_id}, {"$set": {"wm_size": size}}, upsert=True)

    async def get_wm_size(self, user_id):
        user = await self.users.find_one({"_id": user_id})
        return user.get("wm_size") if user else "24"
        
db = Database()
