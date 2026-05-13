import os
import pathlib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload
from contextlib import contextmanager
from sqlalchemy.orm.attributes import instance_state

from .. import config
from ..models.kb_models import Base, KnowledgeDatabase, KnowledgeFile, KnowledgeNode
from ..utils import logger

MYSQL_HOST = "mysql"


class KBDBManager:
    """Knowledge base database manager"""

    def __init__(self):
        self.db_path = os.path.join(config.save_dir, "data", "knowledge.db")
        self.ensure_db_dir()

        # Create SQLAlchemy Engine
        # Prioritize reading of environmental variables, followed by reading of profiles, and finally using reasonable defaults in containers
        mysql_host = os.getenv("MYSQL_HOST", config.get(
            "mysql", {}).get("host", "mysql"))
        mysql_port = int(
            os.getenv("MYSQL_PORT", config.get("mysql", {}).get("port", 3306)))
        mysql_user = os.getenv("MYSQL_USER", config.get(
            "mysql", {}).get("user", "mysql"))
        mysql_password = os.getenv("MYSQL_PASSWORD", config.get(
            "mysql", {}).get("password", "12345678"))
        mysql_db = os.getenv("MYSQL_DB", config.get(
            "mysql", {}).get("database", "knowledge_db"))

        # Build Connection String
        db_url = f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=1800,
        )

        # Create Session Factory
        self.Session = sessionmaker(bind=self.engine)

        # Make sure the watch exists
        self.create_tables()

    def ensure_db_dir(self):
        """Ensure database directory exists"""
        db_dir = os.path.dirname(self.db_path)
        pathlib.Path(db_dir).mkdir(parents=True, exist_ok=True)

    def create_tables(self):
        """Create database table"""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def get_session(self):
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

    def _detach_safely(self, obj):
        """Safe separation of objects，Ensure attribute loaded"""
        if obj is None:
            return None

        # Ensure primary key loaded
        if hasattr(obj, 'id'):
            _ = obj.id
        if hasattr(obj, 'db_id'):
            _ = obj.db_id

        # Add other properties that must be preloaded as necessary

        return obj

    # Knowledge base operating methods
    def get_all_databases(self):
        """Access to all knowledge bases"""
        with self.get_session() as session:
            # Load associated files with eager load
            databases = session.query(KnowledgeDatabase).options(
                joinedload(KnowledgeDatabase.files)
            ).all()

            # Convert to dictionary and return without subsequent delay Load
            return [self._to_dict_safely(db) for db in databases]

    def get_database_by_id(self, db_id):
        """Based onIDAccess to the knowledge base"""
        with self.get_session() as session:
            # Load associated files with eager load
            db = session.query(KnowledgeDatabase).options(
                joinedload(KnowledgeDatabase.files).joinedload(
                    KnowledgeFile.nodes)
            ).filter_by(db_id=db_id).first()

            # Convert to dictionary and return without subsequent delay Load
            return self._to_dict_safely(db) if db else None

    def _to_dict_safely(self, obj):
        """Convert objects safely into dictionaries，Avoiding delay loading problems"""
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    def create_database(self, db_id, name, description, embed_model=None, dimension=None, metadata=None, user_id=None):
        """Create a knowledge base"""
        with self.get_session() as session:
            db = KnowledgeDatabase(
                db_id=db_id,
                name=name,
                description=description,
                embed_model=embed_model,
                dimension=dimension,
                meta_info=metadata or {},  # Store to Meta info field
                user_id=user_id
            )
            session.add(db)
            session.flush()  # Write to database immediately and get ID

            # Manually load necessary data into memory Medium
            db_dict = {
                "db_id": db_id,
                "name": name,
                "description": description,
                "embed_model": embed_model,
                "dimension": dimension,
                "metadata": metadata or {},  # Use metadata on return
                "user_id": user_id,
                "files": {}
            }
            return db_dict

    def delete_database(self, db_id):
        """Remove knowledge base"""
        with self.get_session() as session:
            db = session.query(KnowledgeDatabase).filter_by(
                db_id=db_id).first()
            if db:
                session.delete(db)
                return True
            return False

    # File Operating Method
    def add_file(self, db_id, file_id, filename, path, file_type, status="waiting"):
        """Add File"""
        with self.get_session() as session:
            file = KnowledgeFile(
                file_id=file_id,
                database_id=db_id,
                filename=filename,
                path=path,
                file_type=file_type,
                status=status
            )
            session.add(file)
            session.flush()

            # Return dictionary instead of object to avoid delay loading after session close
            return {
                "file_id": file_id,
                "filename": filename,
                "path": path,
                "type": file_type,
                "status": status,
                "created_at": file.created_at.timestamp() if file.created_at else None,
                "nodes": []
            }

    def update_file_status(self, file_id, status):
        """Update File Status"""
        with self.get_session() as session:
            file = session.query(KnowledgeFile).filter_by(
                file_id=file_id).first()
            if file:
                file.status = status
                return True
            return False

    def delete_file(self, file_id):
        """Delete File"""
        with self.get_session() as session:
            file = session.query(KnowledgeFile).filter_by(
                file_id=file_id).first()
            if file:
                session.delete(file)
                return True
            return False

    def get_files_by_database(self, db_id):
        """Get all files under the knowledge base"""
        with self.get_session() as session:
            files = session.query(KnowledgeFile).options(
                joinedload(KnowledgeFile.nodes)
            ).filter_by(database_id=db_id).all()
            return [self._to_dict_safely(file) for file in files]

    def get_file_by_id(self, file_id):
        """Based onIDGet File"""
        with self.get_session() as session:
            file = session.query(KnowledgeFile).options(
                joinedload(KnowledgeFile.nodes)
            ).filter_by(file_id=file_id).first()
            return self._to_dict_safely(file) if file else None

    # Knowledge Block Operating Method
    def add_node(self, file_id, text, hash_value=None, start_char_idx=None, end_char_idx=None, metadata=None):
        """Add Knowledge Block"""
        with self.get_session() as session:
            node = KnowledgeNode(
                file_id=file_id,
                text=text,
                hash=hash_value,
                start_char_idx=start_char_idx,
                end_char_idx=end_char_idx,
                meta_info=metadata or {}
            )
            session.add(node)
            session.flush()

            # Return dictionary instead of object to avoid delay loading after session close
            return {
                "id": node.id,
                "file_id": file_id,
                "text": text,
                "hash": hash_value,
                "start_char_idx": start_char_idx,
                "end_char_idx": end_char_idx,
                "metadata": metadata or {}
            }

    def get_nodes_by_file(self, file_id):
        """Get all knowledge blocks under the file"""
        with self.get_session() as session:
            nodes = session.query(KnowledgeNode).filter_by(
                file_id=file_id).all()
            return [self._to_dict_safely(node) for node in nodes]

    def get_nodes_by_filter(self, file_id=None, search_text=None, limit=100):
        """Filter the knowledge block by condition"""
        with self.get_session() as session:
            query = session.query(KnowledgeNode)
            if file_id:
                query = query.filter_by(file_id=file_id)
            if search_text:
                query = query.filter(
                    KnowledgeNode.text.like(f"%{search_text}%"))
            nodes = query.limit(limit).all()
            return [self._to_dict_safely(node) for node in nodes]

    def get_user_knowledge_bases(self, user_id):
        """By UserIDAccess to the knowledge base"""

        with self.get_session() as session:
            databases = session.query(
                KnowledgeDatabase).filter_by(user_id=user_id).all()
            return [self._to_dict_safely(db) for db in databases]

    def delete_user_knowledge_bases(self, user_id):
        """By UserIDRemove knowledge base"""
        with self.get_session() as session:
            databases = session.query(
                KnowledgeDatabase).filter_by(user_id=user_id).all()
            for db in databases:
                session.delete(db)
            return True


# Examples of creating a global knowledge base database manager
kb_db_manager = KBDBManager()
