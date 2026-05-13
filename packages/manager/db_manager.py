import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.manager.db_model import Base, User
from packages import config
from packages.utils.logging_config import logger

class DBManager:
    """Database Manager - ProvisionMySQLDatabase connection and session management"""

    def __init__(self):
        # Get MySQL connection information from an environmental variable or configuration
        mysql_host = os.getenv("MYSQL_HOST", "mysql")
        mysql_port = os.getenv("MYSQL_PORT", "3306")
        mysql_db = os.getenv("MYSQL_DB", "knowledge_db")
        mysql_user = os.getenv("MYSQL_USER", "mysql")
        mysql_password = os.getenv("MYSQL_PASSWORD", "12345678")
        
        # Build MySQL connection URL
        self.db_url = f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
        
        # Create SQLAlchemy Engine
        self.engine = create_engine(self.db_url)
        
        # Create Session Factory
        self.Session = sessionmaker(bind=self.engine)
        
        logger.info(f"Database connected to MySQL at {mysql_host}:{mysql_port}")

    def get_session(self):
        """Fetch database sessions"""
        return self.Session()

    @contextmanager
    def get_session_context(self):
        """Context manager for accessing database sessions"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            session.close()

    def check_first_run(self):
        """Check if first run"""
        session = self.get_session()
        try:
            # Check if any users exist
            return session.query(User).count() == 0
        finally:
            session.close()

# Create global database manager instance
db_manager = DBManager()