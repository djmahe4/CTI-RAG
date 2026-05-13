"""General Tool Functions"""

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from packages.manager.db_model import OperationLog, User


def setup_logging():
    """Configure application log format"""
    # Configure log format
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S", force=True
    )

    # Make sure uvicorn logs are in the same format.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_access_logger = logging.getLogger("uvicorn.access")

    # Create Formatter
    formatter = logging.Formatter(fmt="%(asctime)s %(levelname)s: %(message)s", datefmt="%m-%d %H:%M:%S")

    # Set formatting for all processors
    for handler in uvicorn_logger.handlers:
        handler.setFormatter(formatter)
    for handler in uvicorn_access_logger.handlers:
        handler.setFormatter(formatter)


def log_operation(db: Session, user_id: int, operation: str, details: str = None, request: Request = None):
    """Record user operations log"""
    ip_address = None
    if request:
        ip_address = request.client.host if request.client else None

    log = OperationLog(user_id=user_id, operation=operation, details=details, ip_address=ip_address)
    db.add(log)
    db.commit()


def get_user_dict(user: User, include_password: bool = False) -> dict:
    """Get user dictionaries for"""
    return user.to_dict(include_password)


def convert_serializable(obj):
    """Convert objects to serialized formats"""
    if isinstance(obj, list | tuple):
        return [convert_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: convert_serializable(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return convert_serializable(vars(obj))
    return obj