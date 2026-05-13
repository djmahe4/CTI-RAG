import re

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from packages.manager.db_manager import db_manager
from packages.manager.db_model import User
from rag.utils.auth_utils import AuthUtils

# Define OAuth2 password carrier, specify token URL
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

# Open Path List, access without login
PUBLIC_PATHS = [
    r"^/api/auth/token$",  # Login
    r"^/api/auth/check-first-run$",  # Check if first run
    r"^/api/auth/initialize$",  # Initialization System
    r"^/api$",  # Health Check
    r"^/api/system/health$",  # Health Check
    r"^/api/system/info$",  # Get System Info Configuration
]


# Fetch database sessions
def get_db():
    db = db_manager.get_session()
    try:
        yield db
    finally:
        db.close()


# Get Current User
async def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid certificate",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # No token access open path allowed
    if token is None:
        return None

    try:
        # Authenticate token
        payload = AuthUtils.verify_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    except ValueError as e:
        # Capture AuthUtils.verify access tokeen may throw ValueError
        # Like expired or invalid.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),  # Send error information directly to the client End
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Find Users
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


# Retrieving login users (if not login)
async def get_required_user(user: User | None = Depends(get_current_user)):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please check in after login.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Get Administrator Users
async def get_admin_user(current_user: User = Depends(get_required_user)):
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator Permissions Required",
        )
    return current_user


# Fetch Super Administrator Users
async def get_superadmin_user(current_user: User = Depends(get_required_user)):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadminister permission required",
        )
    return current_user


# Check if the path is open
def is_public_path(path: str) -> bool:
    path = path.rstrip("/")  # Remove tail slash to match
    for pattern in PUBLIC_PATHS:
        if re.match(pattern, path):
            return True
    return False