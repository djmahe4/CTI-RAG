"""
UserIDGenerating Tool
Provide username validation anduser_idAuto Generate
"""

import re
import uuid

from pypinyin import lazy_pinyin, Style


def to_pinyin(text: str) -> str:
    """
    Can not open message
    UsepypinyinLibrary for conversion
    """
    # Convert using pypinyin
    pinyin_list = lazy_pinyin(text, style=Style.NORMAL)
    return "".join(pinyin_list)


def validate_username(username: str) -> tuple[bool, str]:
    """
    Authenticate username format

    Args:
        username: Username

    Returns:
        Tuple[bool, str]: (Validity, Error message)
    """
    if not username:
        return False, "Username cannot be empty"

    if len(username) < 2:
        return False, "User name cannot be less than2Character"

    if len(username) > 20:
        return False, "Username cannot be longer than20Character"

    # Check if contains an impermissible character
    # Allow Chinese, English, numbers, underlined
    if not re.match(r"^[\u4e00-\u9fa5a-zA-Z0-9_]+$", username):
        return False, "Usernames can only include Chinese、English、Numbers and Underlined"

    return True, ""


def generate_user_id(username: str) -> str:
    """
    Generate by user nameuser_id，Add prefix to ensure that it is different from the user name
    """
    # Basic clean-up
    username = username.strip()
    
    # 2. Add prefix
    prefix = "uid_"  # Add prefix to ensure that it differs from the user name
    
    # 3. Convert to spelling (if Chinese is included)
    user_id = prefix + to_pinyin(username)
    
    # 4. Processing special characters, retaining only letters, numbers and underlines Line
    user_id = re.sub(r"[^a-zA-Z0-9_]", "", user_id)
    
    # 5. Ensure that numbers do not start
    if user_id and user_id[0].isdigit():
        user_id = "u" + user_id
    
    # 6. Use default prefix if empty or too short
    if len(user_id) < 2:
        user_id = "user" + str(hash(username) % 10000).zfill(4)
    
    # 7. Length limits
    if len(user_id) > 20:
        user_id = user_id[:20]
    
    return user_id.lower()


def is_valid_phone_number(phone: str) -> bool:
    """
    Authenticate cell phone format（Supporting mainland China mobile phone number）

    Args:
        phone: Cell phone string

    Returns:
        bool: Is it a valid cell phone number?
    """
    if not phone:
        return False

    # Remove spaces and special characters
    phone = re.sub(r"[\s\-\(\)]", "", phone)

    # Chinese mainland cell phone number format: 1 at the beginning, 3-9 at the second, 11 places in total
    pattern = r"^1[3-9]\d{9}$"

    return bool(re.match(pattern, phone))


def normalize_phone_number(phone: str) -> str:
    """
    Standardised cell phone format

    Args:
        phone: Original cell number

    Returns:
        str: Standardized cell phone number
    """
    if not phone:
        return ""

    # Remove all non-numeric characters
    phone = re.sub(r"\D", "", phone)

    # If it's a mainland Chinese cell phone, make sure it's the right format.
    if len(phone) == 11 and phone.startswith("1"):
        return phone

    return phone


def generate_int_user_id(db) -> int:
    """
    UseUUIDGenerate10Bit Random Integer as UserID
    
    Args:
        db: Database Session，For inspectionIDExistence
        
    Returns:
        int: 10Integer usersID
    """
    from sqlalchemy import text
    
    while True:
        # Use UUID to generate random numbers and take the last 10 places of their integers
        random_int = abs(uuid.uuid4().int) % 9000000000 + 1000000000
        
        # Make sure the resulting ID is 10 digits.
        user_id = random_int
        
        # Check for presence
        result = db.execute(text("SELECT COUNT(*) FROM users WHERE user_id = :user_id"), 
                           {"user_id": str(user_id)}).scalar()
        
        # If not, return this ID.
        if result == 0:
            return user_id