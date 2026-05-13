import asyncio
import pytest
import sys
import os
import json

# Add root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.cache.redis_session import RedisSessionManager

# Use test Redis URL
TEST_REDIS_URL = "redis://localhost:6379/1"  # Testing using DB 1 to avoid affecting production data

@pytest.fixture
async def redis_session():
    """CreateRedisSession Manager Example"""
    session_manager = RedisSessionManager(redis_url=TEST_REDIS_URL, expire_time=60)
    yield session_manager
    # Clear Test Data
    redis = await session_manager._get_redis()
    await redis.flushdb()
    await session_manager.close()

@pytest.mark.asyncio
async def test_create_session(redis_session):
    """Test Create Session"""
    # Create Session
    session_id = await redis_session.create_session(system_prompt="Test system hints")
    
    # Authentication Session ID format
    assert isinstance(session_id, str)
    assert len(session_id) > 0
    
    # Fetch Session and Verify
    session = await redis_session.get_session(session_id)
    assert session is not None
    assert "history" in session
    assert len(session["history"]) == 1
    assert session["history"][0]["role"] == "system"
    assert session["history"][0]["content"] == "Test system hints"

@pytest.mark.asyncio
async def test_add_message(redis_session):
    """Test Add Message"""
    # Create Session
    session_id = await redis_session.create_session()
    
    # Add User Message
    await redis_session.add_message(session_id, "user", "Hello.")
    
    # Add Assistant Message
    await redis_session.add_message(session_id, "assistant", "Hello. What can I do for you?")
    
    # Get Session History
    history = await redis_session.get_history(session_id)
    
    # Verify history
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello."
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hello. What can I do for you?"

@pytest.mark.asyncio
async def test_delete_session(redis_session):
    """Test Remove Session"""
    # Create Session
    session_id = await redis_session.create_session()
    
    # Authentication session exists
    session = await redis_session.get_session(session_id)
    assert session is not None
    
    # Remove Session
    result = await redis_session.delete_session(session_id)
    assert result is True
    
    # Authentication session deleted
    session = await redis_session.get_session(session_id)
    assert session is None

if __name__ == "__main__":
    asyncio.run(pytest.main(["-xvs", __file__]))