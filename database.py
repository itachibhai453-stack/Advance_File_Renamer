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

db = Database()
