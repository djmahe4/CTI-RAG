import redis.asyncio as redis
import json
import asyncio
from typing import Dict, List, Optional, Any
import uuid
from datetime import datetime, timedelta

class RedisSessionManager:
    """Redis session manager for asynchronously caching session information."""

    def __init__(self, redis_url: str = "redis://localhost:6379", expire_time: int = 3600):
        """Initialize Redis session manager.

        Args:
            redis_url: Redis connection URL.
            expire_time: Session expiration time in seconds.
        """
        self.redis_url = redis_url
        self.expire_time = expire_time
        self.redis = None
        self._connection_lock = asyncio.Lock()

    async def _get_redis(self):
        """Get Redis connection."""
        if self.redis is None:
            async with self._connection_lock:
                if self.redis is None:
                    self.redis = redis.from_url(self.redis_url, decode_responses=True)
        return self.redis

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Retrieve session information.

        Args:
            session_id: The session ID.

        Returns:
            Session information dictionary or None if not found.
        """
        redis = await self._get_redis()
        data = await redis.get(f"session:{session_id}")
        if data:
            # Refresh expiration time
            await redis.expire(f"session:{session_id}", self.expire_time)
            return json.loads(data)
        return None

    async def set_session(self, session_id: str, data: Dict) -> bool:
        """Set session information.

        Args:
            session_id: The session ID.
            data: Session data to store.

        Returns:
            bool: True if successful.
        """
        redis = await self._get_redis()
        await redis.set(
            f"session:{session_id}",
            json.dumps(data),
            ex=self.expire_time
        )
        return True

    async def get_history(self, session_id: str) -> List[Dict]:
        """Retrieve session history.

        Args:
            session_id: The session ID.

        Returns:
            List of session history records.
        """
        session = await self.get_session(session_id)
        if session and "history" in session:
            return session["history"]
        return []

    async def add_message(self, session_id: str, role: str, content: str) -> List[Dict]:
        """Add a message to the session history.

        Args:
            session_id: The session ID.
            role: The role (user/assistant/system).
            content: The message content.

        Returns:
            List: Updated history records.
        """
        session = await self.get_session(session_id) or {"history": []}

        if "history" not in session:
            session["history"] = []

        # Add message
        session["history"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        # Update session
        await self.set_session(session_id, session)
        return session["history"]

    async def create_session(self, system_prompt: str = None) -> str:
        """Create a new session.

        Args:
            system_prompt: Optional system prompt.

        Returns:
            str: The new session ID.
        """
        session_id = str(uuid.uuid4())
        session = {"history": []}

        # If a system prompt is provided, add it to the history
        if system_prompt:
            session["history"].append({
                "role": "system",
                "content": system_prompt,
                "timestamp": datetime.now().isoformat()
            })

        await self.set_session(session_id, session)
        return session_id

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID.

        Returns:
            bool: True if successful.
        """
        redis = await self._get_redis()
        result = await redis.delete(f"session:{session_id}")
        return result > 0

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()