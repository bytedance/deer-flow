# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import yaml
import bcrypt
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

USERS_FILE = Path(__file__).parent.parent.parent / "users.yaml"

# In-memory cache for users
_users_cache: Optional[List['UserConfig']] = None


@dataclass
class UserConfig:
    """User configuration with password hash"""
    id: str
    email: str
    password_hash: str
    name: str
    role: str  # "admin" or "user"


def validate_password(password: str) -> Tuple[bool, str]:
    """
    Validate password meets security requirements.
    Same complexity as JWT secret key but minimum 8 characters.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    # Check for basic complexity - should contain mix of character types
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    
    if not has_upper:
        return False, "Password must contain at least one uppercase letter"
    if not has_lower:
        return False, "Password must contain at least one lowercase letter"
    if not has_digit:
        return False, "Password must contain at least one digit"
    if not has_special:
        return False, "Password must contain at least one special character"
    
    return True, ""


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    password_bytes = password.encode('utf-8')
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    try:
        password_bytes = password.encode('utf-8')
        hash_bytes = password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def load_users() -> List[UserConfig]:
    """Load users from users.yaml file with caching"""
    global _users_cache
    
    if _users_cache is not None:
        return _users_cache
    
    if not USERS_FILE.exists():
        logger.info(f"Users file not found at {USERS_FILE}, starting with empty user list")
        _users_cache = []
        return _users_cache
    
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data or 'users' not in data:
            _users_cache = []
            return _users_cache
        
        users = []
        for user_data in data['users']:
            users.append(UserConfig(
                id=user_data['id'],
                email=user_data['email'],
                password_hash=user_data['password_hash'],
                name=user_data['name'],
                role=user_data['role']
            ))
        
        _users_cache = users
        logger.info(f"Loaded {len(users)} users from {USERS_FILE}")
        return users
    
    except Exception as e:
        logger.error(f"Error loading users from {USERS_FILE}: {e}")
        _users_cache = []
        return _users_cache


def save_users(users: List[UserConfig]) -> bool:
    """Save users to users.yaml file and update cache"""
    global _users_cache
    
    try:
        data = {
            'users': [asdict(user) for user in users]
        }
        
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        
        _users_cache = users
        logger.info(f"Saved {len(users)} users to {USERS_FILE}")
        return True
    
    except Exception as e:
        logger.error(f"Error saving users to {USERS_FILE}: {e}")
        return False


def get_user_by_email(email: str) -> Optional[UserConfig]:
    """Get user by email address"""
    users = load_users()
    for user in users:
        if user.email.lower() == email.lower():
            return user
    return None


def get_user_by_id(user_id: str) -> Optional[UserConfig]:
    """Get user by ID"""
    users = load_users()
    for user in users:
        if user.id == user_id:
            return user
    return None


def get_all_users() -> List[UserConfig]:
    """Get all users"""
    return load_users()


def create_user(email: str, password: str, name: str, role: str = "user") -> Tuple[Optional[UserConfig], str]:
    """
    Create a new user.
    
    Returns:
        Tuple of (user, error_message)
    """
    # Validate email
    if not email or '@' not in email:
        return None, "Invalid email address"
    
    # Check if user already exists
    if get_user_by_email(email):
        return None, "User with this email already exists"
    
    # Validate password
    is_valid, error_msg = validate_password(password)
    if not is_valid:
        return None, error_msg
    
    # Validate role
    if role not in ["admin", "user"]:
        return None, "Role must be 'admin' or 'user'"
    
    # Create user
    users = load_users()
    user_id = f"user_{len(users) + 1}_{email.split('@')[0]}"
    
    new_user = UserConfig(
        id=user_id,
        email=email,
        password_hash=hash_password(password),
        name=name,
        role=role
    )
    
    users.append(new_user)
    
    if save_users(users):
        return new_user, ""
    else:
        return None, "Failed to save user"


def update_user(user_id: str, name: Optional[str] = None, role: Optional[str] = None) -> Tuple[Optional[UserConfig], str]:
    """
    Update user name and/or role.
    
    Returns:
        Tuple of (updated_user, error_message)
    """
    users = load_users()
    
    for i, user in enumerate(users):
        if user.id == user_id:
            if name is not None:
                user.name = name
            if role is not None:
                if role not in ["admin", "user"]:
                    return None, "Role must be 'admin' or 'user'"
                user.role = role
            
            if save_users(users):
                return user, ""
            else:
                return None, "Failed to save user updates"
    
    return None, "User not found"


def delete_user(user_id: str) -> Tuple[bool, str]:
    """
    Delete a user.
    
    Returns:
        Tuple of (success, error_message)
    """
    users = load_users()
    
    # Find the user to delete
    user_to_delete = None
    for user in users:
        if user.id == user_id:
            user_to_delete = user
            break
    
    if not user_to_delete:
        return False, "User not found"
    
    # Check if this is the last admin
    if user_to_delete.role == "admin":
        admin_count = sum(1 for u in users if u.role == "admin")
        if admin_count <= 1:
            return False, "Cannot delete the last admin user"
    
    # Remove user
    users = [u for u in users if u.id != user_id]
    
    if save_users(users):
        return True, ""
    else:
        return False, "Failed to save changes"


def can_delete_user(user_id: str) -> bool:
    """Check if a user can be deleted (not the last admin)"""
    users = load_users()
    
    user_to_check = None
    for user in users:
        if user.id == user_id:
            user_to_check = user
            break
    
    if not user_to_check:
        return False
    
    if user_to_check.role == "admin":
        admin_count = sum(1 for u in users if u.role == "admin")
        return admin_count > 1
    
    return True


def change_password(user_id: str, old_password: str, new_password: str) -> Tuple[bool, str]:
    """
    Change user password.
    
    Returns:
        Tuple of (success, error_message)
    """
    users = load_users()
    
    for i, user in enumerate(users):
        if user.id == user_id:
            # Verify old password
            if not verify_password(old_password, user.password_hash):
                return False, "Current password is incorrect"
            
            # Validate new password
            is_valid, error_msg = validate_password(new_password)
            if not is_valid:
                return False, error_msg
            
            # Update password
            user.password_hash = hash_password(new_password)
            
            if save_users(users):
                return True, ""
            else:
                return False, "Failed to save password change"
    
    return False, "User not found"


def initialize_admin() -> None:
    """
    Initialize admin user from environment variables if no users exist.
    Checks ADMIN_EMAIL and ADMIN_PASSWORD env vars.
    """
    users = load_users()
    
    # Only create admin if no users exist
    if len(users) > 0:
        logger.info(f"Users already exist ({len(users)} users), skipping admin initialization")
        return
    
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    
    if not admin_email or not admin_password:
        logger.warning(
            "No users found and ADMIN_EMAIL/ADMIN_PASSWORD not set. "
            "Please set these environment variables to create initial admin user."
        )
        return
    
    # Create admin user
    admin_user, error = create_user(
        email=admin_email,
        password=admin_password,
        name="Admin",
        role="admin"
    )
    
    if admin_user:
        logger.info(f"Created initial admin user: {admin_email}")
    else:
        logger.error(f"Failed to create admin user: {error}")


def verify_user_credentials(email: str, password: str) -> Optional[dict]:
    """
    Verify user credentials and return user info if valid.
    
    Returns:
        User dict with id, email, name, role if valid, None otherwise
    """
    user = get_user_by_email(email)
    
    if not user:
        return None
    
    if not verify_password(password, user.password_hash):
        return None
    
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role
    }
