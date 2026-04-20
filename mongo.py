from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

class MongoRepo:
    """MongoDB Repository for real estate property operations."""
    
    def __init__(self, uri: str, db_name: str, collection_name: str):
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self.client = None
        self.db = None
        self.collection = None
        
    async def connect(self):
        """Establish async connection to MongoDB."""
        self.client = AsyncIOMotorClient(self.uri)
        self.db = self.client[self.db_name]
        self.collection = self.db[self.collection_name]
        
    async def save_interaction(self, user_id: str, message: str, role: str):
        """Save interaction to MongoDB."""
        if self.db is None:
            await self.connect()
        collection = self.db.interactions
        await collection.insert_one({
            "user_id": user_id,
            "message": message,
            "role": role
        })

    async def search_properties(self, user_query: str, limit: int = 5) -> list[dict]:
        """
        Placeholder property search.
        In a real app, you would use vector search or text search here.
        """
        if self.collection is None:
            await self.connect()
            
        cursor = self.collection.find({}).limit(limit)
        results = await cursor.to_list(length=limit)
        return results
