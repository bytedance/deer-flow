# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.middleware.auth import get_current_user, require_admin_user


# Mock user data
MOCK_USER = {"id": "user_1", "email": "user@test.com", "name": "Test User", "role": "user"}
MOCK_ADMIN = {"id": "admin_1", "email": "admin@test.com", "name": "Admin User", "role": "admin"}


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


@pytest.fixture
def client_user(temp_users_file):
    """Test client with regular user authentication"""
    def mock_get_current_user_func():
        return MOCK_USER
    
    app.dependency_overrides[get_current_user] = mock_get_current_user_func
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_admin(temp_users_file):
    """Test client with admin user authentication"""
    def mock_get_current_user_func():
        return MOCK_ADMIN
    
    def mock_require_admin_user_func():
        return MOCK_ADMIN
    
    app.dependency_overrides[get_current_user] = mock_get_current_user_func
    app.dependency_overrides[require_admin_user] = mock_require_admin_user_func
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestPasswordChangeEndpoint:
    """Test password change endpoint"""

    def test_change_password_success(self, client_user, temp_users_file):
        """Test successful password change"""
        from src.config.users import create_user
        
        # Create a user
        create_user("user@test.com", "OldPass123!@#", "Test User", "user")
        
        # Mock get_current_user to return the created user
        def mock_get_current_user_func():
            return {
                "id": "user_1_user",
                "email": "user@test.com",
                "name": "Test User",
                "role": "user"
            }
        
        app.dependency_overrides[get_current_user] = mock_get_current_user_func
        client = TestClient(app)
        
        response = client.put(
            "/api/auth/password",
            json={
                "old_password": "OldPass123!@#",
                "new_password": "NewPass123!@#"
            }
        )
        
        assert response.status_code == 200
        assert response.json()["message"] == "Password changed successfully"
        
        app.dependency_overrides.clear()

    def test_change_password_wrong_old_password(self, client_user, temp_users_file):
        """Test password change with wrong old password"""
        from src.config.users import create_user
        
        create_user("user@test.com", "OldPass123!@#", "Test User", "user")
        
        def mock_get_current_user_func():
            return {
                "id": "user_1_user",
                "email": "user@test.com",
                "name": "Test User",
                "role": "user"
            }
        
        app.dependency_overrides[get_current_user] = mock_get_current_user_func
        client = TestClient(app)
        
        response = client.put(
            "/api/auth/password",
            json={
                "old_password": "WrongPass123!@#",
                "new_password": "NewPass123!@#"
            }
        )
        
        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"].lower()
        
        app.dependency_overrides.clear()

    def test_change_password_invalid_new_password(self, client_user, temp_users_file):
        """Test password change with invalid new password"""
        from src.config.users import create_user
        
        create_user("user@test.com", "OldPass123!@#", "Test User", "user")
        
        def mock_get_current_user_func():
            return {
                "id": "user_1_user",
                "email": "user@test.com",
                "name": "Test User",
                "role": "user"
            }
        
        app.dependency_overrides[get_current_user] = mock_get_current_user_func
        client = TestClient(app)
        
        response = client.put(
            "/api/auth/password",
            json={
                "old_password": "OldPass123!@#",
                "new_password": "weak"
            }
        )
        
        assert response.status_code == 400
        
        app.dependency_overrides.clear()


class TestListUsersEndpoint:
    """Test list users endpoint"""

    def test_list_users_as_admin(self, client_admin, temp_users_file):
        """Test listing users as admin"""
        from src.config.users import create_user
        
        create_user("user1@test.com", "Test123!@#", "User 1", "user")
        create_user("admin1@test.com", "Test123!@#", "Admin 1", "admin")
        
        response = client_admin.get("/api/admin/users")
        
        assert response.status_code == 200
        users = response.json()
        assert len(users) == 2
        assert all(key in users[0] for key in ["id", "email", "name", "role"])
        assert "password_hash" not in users[0]

    def test_list_users_as_regular_user_forbidden(self, client_user, temp_users_file):
        """Test that regular users cannot list users"""
        # Override to not give admin access
        def mock_require_admin_user_func():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin access required")
        
        app.dependency_overrides[require_admin_user] = mock_require_admin_user_func
        client = TestClient(app)
        
        response = client.get("/api/admin/users")
        
        assert response.status_code == 403
        
        app.dependency_overrides.clear()


class TestCreateUserEndpoint:
    """Test create user endpoint"""

    def test_create_user_success(self, client_admin, temp_users_file):
        """Test successful user creation"""
        response = client_admin.post(
            "/api/admin/users",
            json={
                "email": "newuser@test.com",
                "password": "NewPass123!@#",
                "name": "New User",
                "role": "user"
            }
        )
        
        assert response.status_code == 200
        user = response.json()
        assert user["email"] == "newuser@test.com"
        assert user["name"] == "New User"
        assert user["role"] == "user"
        assert "password" not in user

    def test_create_user_invalid_password(self, client_admin, temp_users_file):
        """Test user creation with invalid password"""
        response = client_admin.post(
            "/api/admin/users",
            json={
                "email": "newuser@test.com",
                "password": "weak",
                "name": "New User",
                "role": "user"
            }
        )
        
        assert response.status_code == 400

    def test_create_user_duplicate_email(self, client_admin, temp_users_file):
        """Test user creation with duplicate email"""
        from src.config.users import create_user
        
        create_user("existing@test.com", "Test123!@#", "Existing User", "user")
        
        response = client_admin.post(
            "/api/admin/users",
            json={
                "email": "existing@test.com",
                "password": "NewPass123!@#",
                "name": "Another User",
                "role": "user"
            }
        )
        
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]


class TestUpdateUserEndpoint:
    """Test update user endpoint"""

    def test_update_user_name(self, client_admin, temp_users_file):
        """Test updating user name"""
        from src.config.users import create_user
        
        user, _ = create_user("user@test.com", "Test123!@#", "Old Name", "user")
        
        response = client_admin.put(
            f"/api/admin/users/{user.id}",
            json={"name": "New Name"}
        )
        
        assert response.status_code == 200
        updated_user = response.json()
        assert updated_user["name"] == "New Name"

    def test_update_user_role(self, client_admin, temp_users_file):
        """Test updating user role"""
        from src.config.users import create_user
        
        user, _ = create_user("user@test.com", "Test123!@#", "Test User", "user")
        
        response = client_admin.put(
            f"/api/admin/users/{user.id}",
            json={"role": "admin"}
        )
        
        assert response.status_code == 200
        updated_user = response.json()
        assert updated_user["role"] == "admin"

    def test_update_user_not_found(self, client_admin, temp_users_file):
        """Test updating non-existent user"""
        response = client_admin.put(
            "/api/admin/users/nonexistent_id",
            json={"name": "New Name"}
        )
        
        assert response.status_code == 400


class TestDeleteUserEndpoint:
    """Test delete user endpoint"""

    def test_delete_user_success(self, client_admin, temp_users_file):
        """Test successful user deletion"""
        from src.config.users import create_user
        
        # Create admin first to avoid last admin issue
        create_user("admin@test.com", "Test123!@#", "Admin", "admin")
        user, _ = create_user("user@test.com", "Test123!@#", "Test User", "user")
        
        response = client_admin.delete(f"/api/admin/users/{user.id}")
        
        assert response.status_code == 200
        assert response.json()["message"] == "User deleted successfully"

    def test_delete_self_forbidden(self, client_admin, temp_users_file):
        """Test that admin cannot delete themselves"""
        response = client_admin.delete("/api/admin/users/admin_1")
        
        assert response.status_code == 400
        assert "Cannot delete your own account" in response.json()["detail"]

    def test_delete_last_admin_forbidden(self, client_admin, temp_users_file):
        """Test that last admin cannot be deleted"""
        from src.config.users import create_user
        
        admin, _ = create_user("admin@test.com", "Test123!@#", "Admin", "admin")
        
        # Try to delete from a different admin context
        def mock_require_admin_user_func():
            return {"id": "different_admin", "email": "different@test.com", "role": "admin"}
        
        app.dependency_overrides[require_admin_user] = mock_require_admin_user_func
        client = TestClient(app)
        
        response = client.delete(f"/api/admin/users/{admin.id}")
        
        assert response.status_code == 400
        assert "last admin" in response.json()["detail"]
        
        app.dependency_overrides.clear()

    def test_delete_user_not_found(self, client_admin, temp_users_file):
        """Test deleting non-existent user"""
        response = client_admin.delete("/api/admin/users/nonexistent_id")
        
        assert response.status_code == 400
