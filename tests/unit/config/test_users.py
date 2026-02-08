# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os


from unittest.mock import patch

import pytest

from src.config.users import (
    UserConfig,
    validate_password,
    hash_password,
    verify_password,
    create_user,
    update_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    get_all_users,
    change_password,
    can_delete_user,
    initialize_admin,
    verify_user_credentials,
    save_users,
    load_users,
)


@pytest.fixture
def temp_users_file(tmp_path):
    """Create a temporary users.yaml file for testing"""
    users_file = tmp_path / "users.yaml"
    with patch("src.config.users.USERS_FILE", users_file):
        # Clear cache before each test
        import src.config.users
        src.config.users._users_cache = None
        yield users_file
        # Clear cache after test
        src.config.users._users_cache = None


class TestPasswordValidation:
    """Test password validation function"""

    def test_valid_password(self):
        """Test that valid password passes validation"""
        is_valid, error = validate_password("Test123!@#")
        assert is_valid is True
        assert error == ""

    def test_password_too_short(self):
        """Test that short password fails"""
        is_valid, error = validate_password("Test1!")
        assert is_valid is False
        assert "at least 8 characters" in error

    def test_password_no_uppercase(self):
        """Test that password without uppercase fails"""
        is_valid, error = validate_password("test123!@#")
        assert is_valid is False
        assert "uppercase letter" in error

    def test_password_no_lowercase(self):
        """Test that password without lowercase fails"""
        is_valid, error = validate_password("TEST123!@#")
        assert is_valid is False
        assert "lowercase letter" in error

    def test_password_no_digit(self):
        """Test that password without digit fails"""
        is_valid, error = validate_password("TestAbc!@#")
        assert is_valid is False
        assert "digit" in error

    def test_password_no_special(self):
        """Test that password without special character fails"""
        is_valid, error = validate_password("Test12345")
        assert is_valid is False
        assert "special character" in error


class TestPasswordHashing:
    """Test password hashing and verification"""

    def test_hash_password(self):
        """Test that password is hashed correctly"""
        password = "Test123!@#"
        hashed = hash_password(password)
        assert hashed != password
        assert len(hashed) > 0

    def test_verify_password_correct(self):
        """Test that correct password verifies"""
        password = "Test123!@#"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password fails verification"""
        password = "Test123!@#"
        wrong_password = "Wrong123!@#"
        hashed = hash_password(password)
        assert verify_password(wrong_password, hashed) is False


class TestUserCRUD:
    """Test user CRUD operations"""

    def test_create_user_success(self, temp_users_file):
        """Test successful user creation"""
        user, error = create_user(
            email="test@example.com",
            password="Test123!@#",
            name="Test User",
            role="user"
        )
        assert user is not None
        assert error == ""
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.role == "user"
        assert user.password_hash != "Test123!@#"

    def test_create_user_invalid_password(self, temp_users_file):
        """Test user creation with invalid password"""
        user, error = create_user(
            email="test@example.com",
            password="weak",
            name="Test User",
            role="user"
        )
        assert user is None
        assert "at least 8 characters" in error

    def test_create_user_duplicate_email(self, temp_users_file):
        """Test that duplicate email fails"""
        create_user("test@example.com", "Test123!@#", "Test User", "user")
        user, error = create_user(
            "test@example.com",
            "Test123!@#",
            "Another User",
            "user"
        )
        assert user is None
        assert "already exists" in error

    def test_create_user_invalid_role(self, temp_users_file):
        """Test that invalid role fails"""
        user, error = create_user(
            "test@example.com",
            "Test123!@#",
            "Test User",
            "superuser"
        )
        assert user is None
        assert "must be 'admin' or 'user'" in error

    def test_get_user_by_email(self, temp_users_file):
        """Test getting user by email"""
        create_user("test@example.com", "Test123!@#", "Test User", "user")
        user = get_user_by_email("test@example.com")
        assert user is not None
        assert user.email == "test@example.com"

    def test_get_user_by_email_not_found(self, temp_users_file):
        """Test getting non-existent user"""
        user = get_user_by_email("nonexistent@example.com")
        assert user is None

    def test_get_user_by_id(self, temp_users_file):
        """Test getting user by ID"""
        created_user, _ = create_user("test@example.com", "Test123!@#", "Test User", "user")
        user = get_user_by_id(created_user.id)
        assert user is not None
        assert user.id == created_user.id

    def test_get_all_users(self, temp_users_file):
        """Test getting all users"""
        create_user("user1@example.com", "Test123!@#", "User 1", "user")
        create_user("user2@example.com", "Test123!@#", "User 2", "admin")
        users = get_all_users()
        assert len(users) == 2

    def test_update_user_name(self, temp_users_file):
        """Test updating user name"""
        created_user, _ = create_user("test@example.com", "Test123!@#", "Old Name", "user")
        updated_user, error = update_user(created_user.id, name="New Name")
        assert updated_user is not None
        assert error == ""
        assert updated_user.name == "New Name"

    def test_update_user_role(self, temp_users_file):
        """Test updating user role"""
        created_user, _ = create_user("test@example.com", "Test123!@#", "Test User", "user")
        updated_user, error = update_user(created_user.id, role="admin")
        assert updated_user is not None
        assert updated_user.role == "admin"

    def test_update_user_invalid_role(self, temp_users_file):
        """Test updating with invalid role"""
        created_user, _ = create_user("test@example.com", "Test123!@#", "Test User", "user")
        updated_user, error = update_user(created_user.id, role="superuser")
        assert updated_user is None
        assert "must be 'admin' or 'user'" in error

    def test_delete_user_success(self, temp_users_file):
        """Test successful user deletion"""
        create_user("admin@example.com", "Test123!@#", "Admin", "admin")
        user, _ = create_user("test@example.com", "Test123!@#", "Test User", "user")
        success, error = delete_user(user.id)
        assert success is True
        assert error == ""
        assert get_user_by_id(user.id) is None

    def test_delete_last_admin_fails(self, temp_users_file):
        """Test that deleting last admin fails"""
        admin, _ = create_user("admin@example.com", "Test123!@#", "Admin", "admin")
        success, error = delete_user(admin.id)
        assert success is False
        assert "last admin" in error

    def test_can_delete_user_regular_user(self, temp_users_file):
        """Test can delete regular user"""
        create_user("admin@example.com", "Test123!@#", "Admin", "admin")
        user, _ = create_user("test@example.com", "Test123!@#", "Test User", "user")
        assert can_delete_user(user.id) is True

    def test_can_delete_user_last_admin(self, temp_users_file):
        """Test cannot delete last admin"""
        admin, _ = create_user("admin@example.com", "Test123!@#", "Admin", "admin")
        assert can_delete_user(admin.id) is False

    def test_can_delete_user_admin_with_others(self, temp_users_file):
        """Test can delete admin when other admins exist"""
        admin1, _ = create_user("admin1@example.com", "Test123!@#", "Admin 1", "admin")
        create_user("admin2@example.com", "Test123!@#", "Admin 2", "admin")
        assert can_delete_user(admin1.id) is True


class TestPasswordChange:
    """Test password change functionality"""

    def test_change_password_success(self, temp_users_file):
        """Test successful password change"""
        user, _ = create_user("test@example.com", "OldPass123!@#", "Test User", "user")
        success, error = change_password(user.id, "OldPass123!@#", "NewPass123!@#")
        assert success is True
        assert error == ""
        # Verify new password works
        assert verify_user_credentials("test@example.com", "NewPass123!@#") is not None

    def test_change_password_wrong_old_password(self, temp_users_file):
        """Test password change with wrong old password"""
        user, _ = create_user("test@example.com", "OldPass123!@#", "Test User", "user")
        success, error = change_password(user.id, "WrongPass123!@#", "NewPass123!@#")
        assert success is False
        assert "incorrect" in error

    def test_change_password_invalid_new_password(self, temp_users_file):
        """Test password change with invalid new password"""
        user, _ = create_user("test@example.com", "OldPass123!@#", "Test User", "user")
        success, error = change_password(user.id, "OldPass123!@#", "weak")
        assert success is False
        assert "at least 8 characters" in error


class TestUserAuthentication:
    """Test user authentication"""

    def test_verify_credentials_success(self, temp_users_file):
        """Test successful credential verification"""
        create_user("test@example.com", "Test123!@#", "Test User", "user")
        user_dict = verify_user_credentials("test@example.com", "Test123!@#")
        assert user_dict is not None
        assert user_dict["email"] == "test@example.com"
        assert user_dict["role"] == "user"

    def test_verify_credentials_wrong_password(self, temp_users_file):
        """Test credential verification with wrong password"""
        create_user("test@example.com", "Test123!@#", "Test User", "user")
        user_dict = verify_user_credentials("test@example.com", "Wrong123!@#")
        assert user_dict is None

    def test_verify_credentials_nonexistent_user(self, temp_users_file):
        """Test credential verification for non-existent user"""
        user_dict = verify_user_credentials("nonexistent@example.com", "Test123!@#")
        assert user_dict is None


class TestAdminInitialization:
    """Test admin user initialization"""

    def test_initialize_admin_creates_user(self, temp_users_file):
        """Test that admin is created when no users exist"""
        with patch.dict(os.environ, {
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "Admin123!@#"
        }):
            initialize_admin()
            user = get_user_by_email("admin@example.com")
            assert user is not None
            assert user.role == "admin"

    def test_initialize_admin_skips_when_users_exist(self, temp_users_file):
        """Test that admin is not created when users already exist"""
        create_user("existing@example.com", "Test123!@#", "Existing User", "user")
        with patch.dict(os.environ, {
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "Admin123!@#"
        }):
            initialize_admin()
            # Should not create admin
            admin = get_user_by_email("admin@example.com")
            assert admin is None

    def test_initialize_admin_no_env_vars(self, temp_users_file):
        """Test that admin is not created without env vars"""
        with patch.dict(os.environ, {}, clear=True):
            initialize_admin()
            users = get_all_users()
            assert len(users) == 0
