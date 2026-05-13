from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import time

Base = declarative_base()

class KnowledgeDatabase(Base):
    """Knowledge base model"""
    __tablename__ = 'knowledge_databases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    db_id = Column(String(255), nullable=False, unique=True, index=True)  # Database ID
    name = Column(String(255), nullable=False)  # Database Name
    description = Column(Text, nullable=True)  # Description
    embed_model = Column(String(255), nullable=True)  # Embedded Model Name
    dimension = Column(Integer, nullable=True)  # Vector Dimension
    meta_info = Column(JSON, nullable=True)  # Metadata
    created_at = Column(DateTime, default=func.now())  # Created
    user_id = Column(String(255), nullable=True, index=True)  # Add userID field


    # Relations
    files = relationship("KnowledgeFile", back_populates="database", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to Dictionary Format，Ensuremeta_infoMap tometadata"""
        result = {
            "id": self.id,
            "db_id": self.db_id,
            "name": self.name,
            "description": self.description,
            "embed_model": self.embed_model,
            "dimension": self.dimension,
            "metadata": self.meta_info or {},  # Make sure the map is right.
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user_id": self.user_id
        }

        # Add File Information
        if self.files:
            result["files"] = {file.file_id: file.to_dict() for file in self.files}
        else:
            result["files"] = {}

        return result

class KnowledgeFile(Base):
    """Knowledge base file model"""
    __tablename__ = 'knowledge_files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(255), nullable=False, unique=True, index=True)  # File ID, add the only limit
    database_id = Column(String(255), ForeignKey('knowledge_databases.db_id'), nullable=False)  # Other Organiser
    filename = Column(String(255), nullable=False)  # Filename
    path = Column(String(1024), nullable=False)  # File Path
    file_type = Column(String(50), nullable=False)  # File type
    status = Column(String(50), nullable=False)  # Process Status
    created_at = Column(DateTime, default=func.now())  # Created

    # Relations
    database = relationship("KnowledgeDatabase", back_populates="files")
    nodes = relationship("KnowledgeNode", back_populates="file", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to Dictionary Format"""
        result = {
            "file_id": self.file_id,
            "database_id": self.database_id,
            "filename": self.filename,
            "path": self.path,
            "type": self.file_type,
            "status": self.status,
            "created_at": self.created_at.timestamp() if self.created_at else time.time()
        }

        # Add Node Information
        if self.nodes:
            result["nodes"] = [node.to_dict() for node in self.nodes]
        else:
            result["nodes"] = []

        return result

class KnowledgeNode(Base):
    """Knowledge block model"""
    __tablename__ = 'knowledge_nodes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(255), ForeignKey('knowledge_files.file_id'), nullable=False)  # Relevant file ID
    text = Column(Text, nullable=False)  # Text Contents
    hash = Column(String(255), nullable=True)  # Text Hash
    start_char_idx = Column(Integer, nullable=True)  # Start Character Index
    end_char_idx = Column(Integer, nullable=True)  # End Character Index
    meta_info = Column(JSON, nullable=True)  # Metadata

    # Relations
    file = relationship("KnowledgeFile", back_populates="nodes")

    def to_dict(self):
        """Convert to Dictionary Format，Ensuremeta_infoMap tometadata"""
        return {
            "id": self.id,
            "file_id": self.file_id,
            "text": self.text,
            "hash": self.hash,
            "start_char_idx": self.start_char_idx,
            "end_char_idx": self.end_char_idx,
            "metadata": self.meta_info or {}  # Make sure the map is right.
        }