from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.manager.db_manager import db_manager
from packages.manager.db_model import User
from rag.utils.auth_middleware import get_admin_user, get_current_user, get_db, get_required_user
from rag.utils.auth_utils import AuthUtils
from rag.utils.user_utils import generate_int_user_id, validate_username, is_valid_phone_number
from rag.utils.common_utils import log_operation


# Create router
auth = APIRouter(prefix="/auth", tags=["authentication"])


# Model for request and response
class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    user_id_login: str  # User id for login
    phone_number: str | None = None
    avatar: str | None = None
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    phone_number: str | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None
    phone_number: str | None = None
    avatar: str | None = None


class UserProfileUpdate(BaseModel):
    phone_number: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    user_id: str
    phone_number: str | None = None
    avatar: str | None = None
    role: str
    created_at: str
    last_login: str | None = None


class InitializeAdmin(BaseModel):
    user_id: str  # Enter user ID directly
    password: str
    phone_number: str | None = None


class UsernameValidation(BaseModel):
    username: str


class UserIdGeneration(BaseModel):
    username: str
    user_id: str
    is_available: bool


# =============================================================================
# == sync, corrected by elderman ==
# =============================================================================


# Route: Login to get tokens
# =============================================================================
# == sync, corrected by elderman ==
# =============================================================================
# Add Request Model
class UserRegister(BaseModel):
    username: str
    password: str
    # phone_number: str | None = None
    captcha: str | None = None  # Optional authentication code field, as required

# Route: User registration
@auth.post("/register", response_model=Token)
async def register_user(
    register_data: UserRegister, 
    request: Request,
    db: Session = Depends(get_db)
):
    """User self-registered interface"""
    
    # Authenticate username
    is_valid, error_msg = validate_username(register_data.username)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )
    
    # Check if a username exists
    existing_user = db.query(User).filter(User.username == register_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    
    # # Check if the cell phone exists (if available)
    # if register_data.phone_number:
    #     if not is_valid_phone_number(register_data.phone_number):
    #         raise HTTPException(
    #             status_code=status.HTTP_400_BAD_REQUEST, 
    # Detail = "Irregular cell phone format."
    #         )
            
    #     existing_phone = db.query(User).filter(User.phone_number == register_data.phone_number).first()
    #     if existing_phone:
    #         raise HTTPException(
    #             status_code=status.HTTP_400_BAD_REQUEST,
    # Detail = "The cell phone number has been registered."
    #         )
    
    # Validate password strength
    if len(register_data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password length cannot be less than8Character",
        )
    
    # Generate 10 random integers as user id
    user_id = str(generate_int_user_id(db))
    
    # Create new user
    hashed_password = AuthUtils.hash_password(register_data.password)
    
    new_user = User(
        username=register_data.username,
        password=hashed_password,  # According to your model, this could be password or password hash.
        user_id=user_id,
        # phone_number=register_data.phone_number,
        role="user",  # Default as Normal User Role
        is_active=True,
        created_at=datetime.now(),
        last_login=datetime.now()
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Generate access tokens
    token_data = {"sub": str(new_user.id)}
    access_token = AuthUtils.create_access_token(token_data)
    
    # Record Operations
    log_operation(db, new_user.id, "User Registration", f"User {register_data.username} Registration completed")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_user.id,
        "username": new_user.username,
        "user_id_login": str(new_user.user_id) if new_user.user_id else str(new_user.id),
        "role": new_user.role
    }

@auth.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Find User - Support username login
    login_identifier = form_data.username
    
    # Find by username
    user = db.query(User).filter(User.username == login_identifier).first()
    
    # Returns generic error information if the user does not exist
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error with username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user activated
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is locked in login
    if user.is_login_locked():
        remaining_time = user.get_remaining_lock_time()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Login Locked，Please wait. {remaining_time} Try again in seconds.",
            headers={"WWW-Authenticate": "Bearer", "X-Lock-Remaining": str(remaining_time)},
        )
    
    # Authentication password - direct comparison of password fields (assuming the password is stored by Hash)
    if not AuthUtils.verify_password(user.password, form_data.password):
        # Password error, increase number of failures
        user.increment_failed_login()
        db.commit()
        
        # Record failed operation
        log_operation(db, user.id if user else None, "Login Failed", f"Password error，Number of failures: {user.login_failed_count}")
        
        # Check if locking is required
        if user.is_login_locked():
            remaining_time = user.get_remaining_lock_time()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Due to multiple login failures，Account locked {remaining_time} sec",
                headers={"WWW-Authenticate": "Bearer", "X-Lock-Remaining": str(remaining_time)},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Error with username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # Login successful, reset failed counter
    user.reset_failed_login()
    user.last_login = datetime.now()
    db.commit()
    
    # Generate access tokens
    token_data = {"sub": str(user.id)}
    access_token = AuthUtils.create_access_token(token_data)
    
    # Record login operation
    log_operation(db, user.id, "Login")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.username,
        "user_id_login": str(user.user_id) if user.user_id else str(user.id),
        "role": user.role,
    }


# Route: Verify whether the initialization administrator is required
@auth.get("/check-first-run")
async def check_first_run():
    is_first_run = db_manager.check_first_run()
    return {"first_run": is_first_run}


# Route: Initialization of administrator accounts
@auth.post("/initialize", response_model=Token)
async def initialize_admin(admin_data: InitializeAdmin, db: Session = Depends(get_db)):
    # Check if it's first run
    if not db_manager.check_first_run():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The system has been initialized，Could not create initial administrator again",
        )

    # Create Administrator Account
    hashed_password = AuthUtils.hash_password(admin_data.password)

    # Authenticate user ID format (letter numbers and underlineds only)
    if not re.match(r"^[a-zA-Z0-9_]+$", admin_data.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UserIDOnly include letters、Numbers and Underlined",
        )

    if len(admin_data.user_id) < 3 or len(admin_data.user_id) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UserIDThe length must be3-20Between Characters",
        )

    # Authentication of cell phone number format (if available)
    if admin_data.phone_number and not is_valid_phone_number(admin_data.phone_number):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The cell phone format is incorrect.")

    # As initialization, direct use of input 'ser id '
    user_id = admin_data.user_id

    new_admin = User(
        username=admin_data.user_id,  # Set username and user id to the same value
        user_id=user_id,
        phone_number=admin_data.phone_number,
        avatar=None,  # When initializing, the head looks empty.
        password_hash=hashed_password,
        role="superadmin",
        last_login=datetime.now(),
    )

    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    # Generate access tokens
    token_data = {"sub": str(new_admin.id)}
    access_token = AuthUtils.create_access_token(token_data)

    # Record Operations
    log_operation(db, new_admin.id, "System Initialization", "Create Super Administrator Account")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": new_admin.id,
        "username": new_admin.username,
        "user_id_login": new_admin.user_id,
        "phone_number": new_admin.phone_number,
        "avatar": new_admin.avatar,
        "role": new_admin.role,
    }


# Route: Get current user information
# =============================================================================
# == sync, corrected by elderman ==
# =============================================================================


@auth.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user.to_dict()


# Route: Update personal data
@auth.put("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_required_user),
    db: Session = Depends(get_db),
):
    """Update personal data of current user"""
    update_details = []

    # Update cell number
    if profile_data.phone_number is not None:
        # If the cell phone is not empty, verify the format
        if profile_data.phone_number and not is_valid_phone_number(profile_data.phone_number):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The cell phone format is incorrect.")

        # Check if cell phone numbers are already used by other users
        if profile_data.phone_number:
            existing_phone = (
                db.query(User)
                .filter(User.phone_number == profile_data.phone_number, User.id != current_user.id)
                .first()
            )
            if existing_phone:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The cell phone has been used by other users")

        current_user.phone_number = profile_data.phone_number
        update_details.append(f"Cell phone number: {profile_data.phone_number or 'Cleared'}")

    db.commit()

    # Record Operations
    if update_details:
        log_operation(db, current_user.id, "Update of personal data", f"Update of personal data: {', '.join(update_details)}", request)

    return current_user.to_dict()


# Route: Create new user (administrator privileges)
# =============================================================================
# == sync, corrected by elderman ==
# =============================================================================


@auth.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate, request: Request, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    # Authenticate username
    is_valid, error_msg = validate_username(user_data.username)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Check if a username exists
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Check if cell phone number exists (if available)
    if user_data.phone_number:
        existing_phone = db.query(User).filter(User.phone_number == user_data.phone_number).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cell phone already exists.",
            )

    # Generate 10 random integers as user id
    user_id = str(generate_int_user_id(db))

    # Create new user
    hashed_password = AuthUtils.hash_password(user_data.password)

    # Check Role Permissions
    # Superadministers can create any type of user
    if user_data.role == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a superman can create a superman account.",
        )

    # The administrator can only create normal users
    if current_user.role == "admin" and user_data.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The administrator can only create ordinary user accounts",
        )

    new_user = User(
        username=user_data.username,
        user_id=user_id,
        phone_number=user_data.phone_number,
        password_hash=hashed_password,
        role=user_data.role,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Record Operations
    log_operation(db, current_user.id, "Create User", f"Create User: {user_data.username}, Role: {user_data.role}", request)

    return new_user.to_dict()


# Route: Access to all users (administrator privileges)
@auth.get("/users", response_model=list[UserResponse])
async def read_users(
    skip: int = 0, limit: int = 100, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    users = db.query(User).offset(skip).limit(limit).all()
    return [user.to_dict() for user in users]


# Route: Access to specific user information (administrator privileges)
@auth.get("/users/{user_id}", response_model=UserResponse)
async def read_user(user_id: int, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not exist",
        )
    return user.to_dict()


# Route: Update user information (administrator privileges)
@auth.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not exist",
        )

    # Inspection Permissions
    if user.role == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a superman can modify the Superman account.",
        )

    # Super Administrator accounts cannot be downgraded (can only be modified by other Super Administrators)
    if user.role == "superadmin" and user_data.role and user_data.role != "superadmin" and current_user.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can't downgrade the Super Administrator's account.",
        )

    # Update Information
    update_details = []

    if user_data.username is not None:
        # Check if the username is already used by other users
        existing_user = db.query(User).filter(User.username == user_data.username, User.id != user_id).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )
        user.username = user_data.username
        update_details.append(f"Username: {user_data.username}")

    if user_data.password is not None:
        user.password_hash = AuthUtils.hash_password(user_data.password)
        update_details.append("Password updated")

    if user_data.role is not None:
        user.role = user_data.role
        update_details.append(f"Role: {user_data.role}")

    db.commit()

    # Record Operations
    log_operation(db, current_user.id, "Update User", f"Update UserID {user_id}: {', '.join(update_details)}", request)

    return user.to_dict()


# Route: Delete user (administrator privileges)
@auth.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: int, request: Request, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not exist",
        )

    # Inspection Permissions
    if user.role == "superadmin":
        # Only a superman can remove a superman.
        if current_user.role != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the Super Administrator can delete the Super Administrator's account.",
            )

        # Check if it's the last superman.
        superadmin_count = db.query(User).filter(User.role == "superadmin").count()
        if superadmin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can't delete the last Super Administrator account.",
            )

    # Could not close temporary folder: %s
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not close temporary folder: %s",
        )

    # Record Operations
    log_operation(
        db, current_user.id, "Remove User", f"Remove User: {user.username}, ID: {user.id}, Role: {user.role}", request
    )

    # Remove User
    db.delete(user)
    db.commit()

    return {"success": True, "message": "User deleted"}


# Route: Verify username and generate user id
@auth.post("/validate-username", response_model=UserIdGeneration)
async def validate_username_and_generate_user_id(
    validation_data: UsernameValidation, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Verify username format and generate availableuser_id"""
    # Authenticate username format
    is_valid, error_msg = validate_username(validation_data.username)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Check if a username exists
    existing_user = db.query(User).filter(User.username == validation_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Generate 10 random integers as user id
    user_id = str(generate_int_user_id(db))

    return UserIdGeneration(username=validation_data.username, user_id=user_id, is_available=True)


# Route: Check if user id is available
@auth.get("/check-user-id/{user_id}")
async def check_user_id_availability(
    user_id: str, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Inspectionuser_idAvailable"""
    existing_user = db.query(User).filter(User.user_id == user_id).first()
    return {"user_id": user_id, "is_available": existing_user is None}


# # Route: upload user headers
# @auth.post("/upload-avatar")
# async def upload_user_avatar(
#     file: UploadFile = File(...), current_user: User = Depends(get_required_user), db: Session = Depends(get_db)
# ):
# """"""""""""
# # Check file type
#     if not file.content_type or not file.content_type.startswith("image/"):
# Rice HTTPException (status code=status.HTTP 400 BAD REQUEST, detail= "Only upload photo files")

# # Check file size (5MB limit)
#     file_size = 0
#     file_content = await file.read()
#     file_size = len(file_content)

#     if file_size > 5 * 1024 * 1024:  # 5MB
# Rice HTTPException (status code=status.HTTP 400 BAD REQUEST, detail= "File size cannot exceed 5MB")

#     try:
# # Get File Extension
#         file_extension = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "jpg"

# # Upload to MinIO
#         avatar_url = upload_image_to_minio(file_content, file_extension)

# # Update user image
#         current_user.avatar = avatar_url
#         db.commit()

# # Record operation
# log operation (db, current user.id, "upload" and "f" update: {avartar url})

# True, "avatar url": avartar url, "message": "head upload success"

#     except Exception as e:
# Raise HTTPException (status code=status.HTTP 500 INTERNAL SERVER ERRO, detail=f "Package Upload Failed: {str(e)}")
