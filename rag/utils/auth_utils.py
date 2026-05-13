import hashlib
# rag/utils/auth_utils.py
import os
from datetime import datetime, timedelta
from typing import Dict, Any
from jose import jwt
from passlib.context import CryptContext


class AuthUtils:
    # Password Hash Tool
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    # JWT Configuration
    SECRET_KEY = os.getenv("JWT_SECRET_KEY", "br-chat-aision")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

    @classmethod
    def verify_password(cls, stored_password, plain_password):
        """Authentication password"""
        # If the password stored is a Hash value, verify it with Hash
        if (stored_password.startswith("$2b$") or
            stored_password.startswith("$2a$") or
                stored_password.startswith("$pbkdf2-sha256$")):  # Fix prefix check here
            return cls.pwd_context.verify(plain_password, stored_password)
        # If explicit password (not recommended), direct comparison
        return stored_password == plain_password

    @classmethod
    def hash_password(cls, password):
        """Hash password."""
        # Debug Information
        print(f"Password Length: {len(password)} Character, {len(password.encode('utf-8'))} Bytes")

        # Make sure it doesn't exceed 72 bytes.
        password_bytes = password.encode(
            'utf-8') if isinstance(password, str) else password
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
            password = password_bytes.decode(
                'utf-8') if isinstance(password, bytes) else password[:72]

        return cls.pwd_context.hash(password)

    @classmethod
    def create_access_token(cls, data: Dict):
        """Create access tokens"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=cls.ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(
            to_encode, cls.SECRET_KEY, algorithm=cls.ALGORITHM)
        return encoded_jwt

    @classmethod
    def decode_token(cls, token: str):
        """Decoding tokens"""
        try:
            payload = jwt.decode(token, cls.SECRET_KEY,
                                 algorithms=[cls.ALGORITHM])
            return payload
        except jwt.PyJWTError:
            return None

    @staticmethod
    def verify_access_token(token: str) -> dict[str, Any]:
        """Authenticate access tokens，If it doesn't work, throw out the anomaly."""
        try:
            # Fix here, use the AuthUtils class variable
            payload = jwt.decode(token, AuthUtils.SECRET_KEY,
                                 algorithms=[AuthUtils.ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("The token expired.")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")
