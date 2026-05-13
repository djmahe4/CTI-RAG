"""
Chat Session Manager - Integration MySQL Main Storage and Redis Cache
"""
import json
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from packages.manager.db_model import ChatSession, ChatMessage, User
from packages.manager.db_manager import db_manager
from packages.utils.logging_config import logger


class ChatSessionManager:
    """Chat Session Manager - MySQLAs Primary Storage，RedisAs Cache"""

    def __init__(self, redis_manager=None):
        """Initialising Session Manager
        
        Args:
            redis_manager: RedisSession Manager Example（Optional）
        """
        self.redis_manager = redis_manager
        self.cache_expire_time = 3600  # Redis cache 1 hour

    def _get_cache_key(self, session_id: str) -> str:
        """AccessRedisCache keys"""
        return f"chat_session:{session_id}"

    async def create_session(
        self,
        user_id: int,
        title: str = None,
        system_prompt: str = None
    ) -> str:
        """Create a new session
        
        Args:
            user_id: UserID
            title: Session Title（Optional，Max50Character）
            system_prompt: System Hint（Optional）
            
        Returns:
            New SessionID (UUIDFormat)
        """
        session_id = str(uuid.uuid4())
        
        try:
            with db_manager.get_session_context() as db_session:
                # Generate Default Title
                default_title = f"Dialogue {datetime.now().strftime('%m-%d %H:%M')}"
                
                # Ensure that the title does not exceed 50 words Arguments
                if title:
                    title = title[:50] if len(title) > 50 else title
                else:
                    title = default_title
                
                # Create Session Record
                new_session = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    title=title,
                    system_prompt=system_prompt
                )
                db_session.add(new_session)
                db_session.flush()
                
                # Add the first message if there is a systematic hint
                if system_prompt:
                    system_msg = ChatMessage(
                        session_id=session_id,
                        role="system",
                        content=system_prompt
                    )
                    db_session.add(system_msg)
                
                db_session.commit()
                
                logger.info(f"Successfully created new session: session_id={session_id}, user_id={user_id}")
                
                # Cache to Redis
                if self.redis_manager:
                    session_data = {
                        "session_id": session_id,
                        "user_id": user_id,
                        "title": new_session.title,
                        "system_prompt": system_prompt,
                        "history": [{"role": "system", "content": system_prompt}] if system_prompt else []
                    }
                    await self.redis_manager.set_session(session_id, session_data)
                
                return session_id
                
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    async def get_session(
        self,
        session_id: str,
        user_id: int = None,
        include_messages: bool = False
    ) -> Optional[Dict]:
        """Fetch Session Information（FirstRedisCha.，FromMySQLCha.）
        
        Args:
            session_id: SessionID
            user_id: UserID（Optional，For Permission Validation）
            include_messages: Can not open message
            
        Returns:
            Session Information Dictionary orNone
        """
        # 1. Try to get first from Redis
        if self.redis_manager and not include_messages:
            try:
                cached_session = await self.redis_manager.get_session(session_id)
                if cached_session:
                    # Verify User Permissions
                    if user_id and cached_session.get("user_id") != user_id:
                        logger.warning(f"User {user_id} No access to session {session_id}")
                        return None
                    logger.debug(f"FromRedisCache Fetch Session: {session_id}")
                    return cached_session
            except Exception as e:
                logger.warning(f"FromRedisFailed to fetch session: {e}")
        
        # 2. Access from MySQL
        try:
            with db_manager.get_session_context() as db_session:
                query = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.is_deleted == 0
                )
                
                # Add permission filter if user id is provided
                if user_id:
                    query = query.filter(ChatSession.user_id == user_id)
                
                session = query.first()
                
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return None
                
                session_data = session.to_dict(include_messages=include_messages)
                
                logger.debug(f"FromMySQLFetch Session: {session_id}")
                
                # Can not open message
                if self.redis_manager and not include_messages:
                    await self.redis_manager.set_session(session_id, session_data)
                
                return session_data
                
        except Exception as e:
            logger.error(f"Failed to fetch session: {e}")
            return None

    async def get_history(
        self,
        session_id: str,
        user_id: int = None,
        limit: int = None
    ) -> List[Dict]:
        """Fetch Session History Message（FirstRedisCha.，FromMySQLCha.）
        
        Args:
            session_id: SessionID
            user_id: UserID（Optional，For Permission Validation）
            limit: Limit the number of returns（Optional）
            
        Returns:
            Message List
        """
        # 1. Try to get first from Redis
        if self.redis_manager:
            try:
                cached_history = await self.redis_manager.get_history(session_id)
                if cached_history:
                    # Simple permission to verify: access user id through session
                    session = await self.redis_manager.get_session(session_id)
                    if session and (not user_id or session.get("user_id") == user_id):
                        logger.debug(f"FromRedisCache For History: {session_id}, {len(cached_history)} Message")
                        if limit:
                            return cached_history[-limit:]
                        return cached_history
            except Exception as e:
                logger.warning(f"FromRedisFailed to capture history: {e}")
        
        # 2. Access from MySQL
        try:
            with db_manager.get_session_context() as db_session:
                # Authenticate Session Permissions
                session_query = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.is_deleted == 0
                )
                if user_id:
                    session_query = session_query.filter(ChatSession.user_id == user_id)
                
                session = session_query.first()
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return []
                
                # Query Message
                messages_query = db_session.query(ChatMessage).filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.is_deleted == 0
                ).order_by(ChatMessage.created_at)
                
                if limit:
                    # Get Recent N Messages
                    messages_query = messages_query.order_by(desc(ChatMessage.created_at)).limit(limit)
                    messages = list(reversed(messages_query.all()))
                else:
                    messages = messages_query.all()
                
                history = [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None
                    }
                    for msg in messages
                ]
                
                logger.debug(f"FromMySQLGet History: {session_id}, {len(history)} Message")
                
                # Cache to Redis
                if self.redis_manager:
                    session_data = {
                        "session_id": session_id,
                        "user_id": session.user_id,
                        "title": session.title,
                        "system_prompt": session.system_prompt,
                        "history": history
                    }
                    await self.redis_manager.set_session(session_id, session_data)
                
                return history
                
        except Exception as e:
            logger.error(f"Failed to retrieve historical messages: {e}")
            return []

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: int = None,
        meta: Dict = None
    ) -> bool:
        """Can not open message（Writing simultaneouslyMySQLandRedis）
        
        Args:
            session_id: SessionID
            role: Role (user/assistant/system)
            content: Message Contents
            user_id: UserID（Optional，For Permission Validation）
            meta: Extra metadata（Optional）
            
        Returns:
            Success
        """
        try:
            # 1. Writing MySQL
            with db_manager.get_session_context() as db_session:
                # Verify Session Permissions
                session_query = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.is_deleted == 0
                )
                if user_id:
                    session_query = session_query.filter(ChatSession.user_id == user_id)
                
                session = session_query.first()
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return False
                
                # Can not open message
                new_message = ChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    meta=json.dumps(meta) if meta else None
                )
                db_session.add(new_message)
                
                # Updateed session
                session.updated_at = datetime.now()
                
                db_session.commit()
                
                logger.debug(f"Can not open messageMySQL: session={session_id}, role={role}")
            
            # Update the Redis cache
            if self.redis_manager:
                try:
                    await self.redis_manager.add_message(session_id, role, content)
                    logger.debug(f"Can not open messageRedisCache: session={session_id}, role={role}")
                except Exception as e:
                    logger.warning(f"UpdateRedisCache Failed: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Can not open message: {e}")
            return False

    async def update_session(
        self,
        session_id: str,
        user_id: int,
        title: str = None,
        system_prompt: str = None
    ) -> bool:
        """Update Session Information
        
        Args:
            session_id: SessionID
            user_id: UserID
            title: New Title（Optional，Max50Character）
            system_prompt: New System Hint（Optional）
            
        Returns:
            Success
        """
        try:
            with db_manager.get_session_context() as db_session:
                session = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.user_id == user_id,
                    ChatSession.is_deleted == 0
                ).first()
                
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return False
                
                if title is not None:
                    # Ensure that the title does not exceed 50 words Arguments
                    session.title = title[:50] if len(title) > 50 else title
                if system_prompt is not None:
                    session.system_prompt = system_prompt
                
                session.updated_at = datetime.now()
                db_session.commit()
                
                logger.info(f"Update session successfully: {session_id}")
                
                # Clear Redis cache, reload next visit
                if self.redis_manager:
                    try:
                        await self.redis_manager.delete_session(session_id)
                    except Exception as e:
                        logger.warning(f"ClearRedisCache Failed: {e}")
                
                return True
                
        except Exception as e:
            logger.error(f"Update session failed: {e}")
            return False

    async def delete_session(
        self,
        session_id: str,
        user_id: int,
        hard_delete: bool = False
    ) -> bool:
        """Remove Session（Soft or hard to delete）
        
        Args:
            session_id: SessionID
            user_id: UserID
            hard_delete: Delete Hardly（Default Soft Delete）
            
        Returns:
            Success
        """
        try:
            with db_manager.get_session_context() as db_session:
                session = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.user_id == user_id
                ).first()
                
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return False
                
                if hard_delete:
                    # Hard Delete: Physical Delete Record
                    db_session.delete(session)
                    logger.info(f"Hardly delete session: {session_id}")
                else:
                    # Soft Delete: mark as deleted
                    session.is_deleted = 1
                    session.updated_at = datetime.now()
                    logger.info(f"Soft Delete Session: {session_id}")
                
                db_session.commit()
                
                # Remove Redis Cache
                if self.redis_manager:
                    try:
                        await self.redis_manager.delete_session(session_id)
                        logger.debug(f"DeleteRedisCache: {session_id}")
                    except Exception as e:
                        logger.warning(f"DeleteRedisCache Failed: {e}")
                
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    async def list_user_sessions(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[Dict]:
        """Can not open message
        
        Args:
            user_id: UserID
            limit: Limited number
            offset: Offset
            include_deleted: Whether to include deleted sessions
            
        Returns:
            Session List
        """
        try:
            with db_manager.get_session_context() as db_session:
                query = db_session.query(ChatSession).filter(
                    ChatSession.user_id == user_id
                )
                
                if not include_deleted:
                    query = query.filter(ChatSession.is_deleted == 0)
                
                sessions = query.order_by(
                    desc(ChatSession.updated_at)
                ).limit(limit).offset(offset).all()
                
                result = [session.to_dict(include_messages=False) for session in sessions]
                
                logger.debug(f"Get Users {user_id} Organisation: {len(result)} individual")
                
                return result
                
        except Exception as e:
            logger.error(f"Failed to fetch user session list: {e}")
            return []

    async def delete_message(
        self,
        message_id: int,
        session_id: str,
        user_id: int
    ) -> bool:
        """Can not open message（Soft Delete）
        
        Args:
            message_id: MessageID
            session_id: SessionID
            user_id: UserID
            
        Returns:
            Success
        """
        try:
            with db_manager.get_session_context() as db_session:
                # Authentication Permissions
                session = db_session.query(ChatSession).filter(
                    ChatSession.session_id == session_id,
                    ChatSession.user_id == user_id,
                    ChatSession.is_deleted == 0
                ).first()
                
                if not session:
                    logger.warning(f"Session does not exist or has no access: {session_id}")
                    return False
                
                # Can not open message
                message = db_session.query(ChatMessage).filter(
                    ChatMessage.id == message_id,
                    ChatMessage.session_id == session_id
                ).first()
                
                if not message:
                    logger.warning(f"Message does not exist: {message_id}")
                    return False
                
                message.is_deleted = 1
                session.updated_at = datetime.now()
                
                db_session.commit()
                
                logger.info(f"Can not open message: message_id={message_id}")
                
                # Clear Redis cache
                if self.redis_manager:
                    try:
                        await self.redis_manager.delete_session(session_id)
                    except Exception as e:
                        logger.warning(f"ClearRedisCache Failed: {e}")
                
                return True
                
        except Exception as e:
            logger.error(f"Can not open message: {e}")
            return False


# Create global session manager instance (injecting Redis manager at initialization in API)
chat_session_manager = None


def get_chat_session_manager(redis_manager=None):
    """Fetch Session Manager Example（Single case mode）"""
    global chat_session_manager
    if chat_session_manager is None:
        chat_session_manager = ChatSessionManager(redis_manager=redis_manager)
    return chat_session_manager

