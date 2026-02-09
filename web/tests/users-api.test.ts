import {
  fetchUsers,
  createUser,
  updateUser,
  deleteUser,
  changePassword,
} from '../src/core/api/users';
import type { User, CreateUserRequest, UpdateUserRequest, ChangePasswordRequest } from '../src/core/api/users';

// Mock the global fetch
global.fetch = jest.fn();

// Mock the auth utils
jest.mock('~/core/auth/utils', () => ({
  getAuthHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));

// Mock the resolve service URL
jest.mock('../src/core/api/resolve-service-url', () => ({
  resolveServiceURL: jest.fn((path: string) => `http://localhost:8000/api/${path}`),
}));

describe('User API', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  describe('fetchUsers', () => {
    it('should fetch users successfully', async () => {
      const mockUsers: User[] = [
        {
          id: '1',
          email: 'user1@test.com',
          name: 'User 1',
          role: 'user',
        },
        {
          id: '2',
          email: 'admin@test.com',
          name: 'Admin User',
          role: 'admin',
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockUsers,
      });

      const users = await fetchUsers();

      expect(users).toEqual(mockUsers);
    });

    it('should throw error on failed request', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Unauthorized' }),
      });

      await expect(fetchUsers()).rejects.toThrow();
    });
  });

  describe('createUser', () => {
    it('should create user successfully', async () => {
      const newUserData: CreateUserRequest = {
        email: 'newuser@test.com',
        password: 'SecurePass123!',
        name: 'New User',
        role: 'user',
      };

      const createdUser: User = {
        id: '3',
        email: newUserData.email,
        name: newUserData.name,
        role: newUserData.role,
      };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => createdUser,
      });

      const user = await createUser(newUserData);

      expect(user).toEqual(createdUser);
    });

    it('should throw error on validation failure', async () => {
      const invalidUserData: CreateUserRequest = {
        email: 'invalid@test.com',
        password: 'weak',
        name: 'Invalid User',
        role: 'user',
      };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Password too weak' }),
      });

      await expect(createUser(invalidUserData)).rejects.toThrow('Password too weak');
    });
  });

  describe('updateUser', () => {
    it('should update user name successfully', async () => {
      const userId = '1';
      const updateData: UpdateUserRequest = {
        name: 'Updated Name',
      };

      const updatedUser: User = {
        id: userId,
        email: 'user@test.com',
        name: updateData.name!,
        role: 'user',
      };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => updatedUser,
      });

      const user = await updateUser(userId, updateData);

      expect(user).toEqual(updatedUser);
    });

    it('should update user role successfully', async () => {
      const userId = '1';
      const updateData: UpdateUserRequest = {
        role: 'admin',
      };

      const updatedUser: User = {
        id: userId,
        email: 'user@test.com',
        name: 'User Name',
        role: 'admin',
      };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => updatedUser,
      });

      const user = await updateUser(userId, updateData);

      expect(user.role).toBe('admin');
    });

    it('should throw error when user not found', async () => {
      const userId = 'nonexistent';
      const updateData: UpdateUserRequest = {
        name: 'New Name',
      };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'User not found' }),
      });

      await expect(updateUser(userId, updateData)).rejects.toThrow();
    });
  });

  describe('deleteUser', () => {
    it('should delete user successfully', async () => {
      const userId = '1';

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'User deleted successfully' }),
      });

      await deleteUser(userId);

      expect(global.fetch).toHaveBeenCalled();
    });

    it('should throw error when deleting self', async () => {
      const userId = 'self';

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Cannot delete your own account' }),
      });

      await expect(deleteUser(userId)).rejects.toThrow('Cannot delete your own account');
    });

    it('should throw error when deleting last admin', async () => {
      const userId = 'admin';

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Cannot delete the last admin' }),
      });

      await expect(deleteUser(userId)).rejects.toThrow('Cannot delete the last admin');
    });
  });

  describe('changePassword', () => {
    it('should change password successfully', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Password changed successfully' }),
      });

      await changePassword('OldPass123!', 'NewPass123!');

      expect(global.fetch).toHaveBeenCalled();
    });

    it('should throw error when old password is incorrect', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Old password is incorrect' }),
      });

      await expect(changePassword('WrongPass123!', 'NewPass123!')).rejects.toThrow('Old password is incorrect');
    });

    it('should throw error when new password is invalid', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Password does not meet requirements' }),
      });

      await expect(changePassword('OldPass123!', 'weak')).rejects.toThrow('Password does not meet requirements');
    });
  });
});
