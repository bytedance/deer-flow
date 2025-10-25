// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * Tests for Issue #588 Fix: Message ID Management and Filtering
 * 
 * These tests verify the core logic for:
 * - Preventing duplicate message IDs
 * - Filtering renderable messages
 * - Handling tool call results
 */

import type { Message } from '~/core/messages';

/**
 * Helper function to test duplicate prevention logic
 * Simulates the appendMessage behavior
 */
function appendMessageWithDuplicatePrevention(
  messageIds: string[],
  messageId: string
): string[] {
  if (!messageIds.includes(messageId)) {
    return [...messageIds, messageId];
  }
  return messageIds;
}

/**
 * Helper function to filter renderable messages
 * Simulates useRenderableMessageIds logic
 */
function filterRenderableMessageIds(
  messageIds: string[],
  messages: Map<string, Message>,
  researchIds: string[]
): string[] {
  return messageIds.filter((messageId) => {
    const message = messages.get(messageId);
    if (!message) return false;
    
    // Only include messages that will actually render in MessageListView
    return (
      message.role === 'user' ||
      message.agent === 'coordinator' ||
      message.agent === 'planner' ||
      message.agent === 'podcast' ||
      researchIds.includes(messageId)
    );
  });
}

/**
 * Helper function to find message by tool call ID
 */
function findMessageByToolCallId(
  toolCallId: string,
  messages: Map<string, Message>
): Message | undefined {
  for (const message of messages.values()) {
    if (message.toolCalls?.some((tc) => tc.id === toolCallId)) {
      return message;
    }
  }
  return undefined;
}

describe('Issue #588: Message ID Management and Filtering', () => {
  describe('Duplicate Prevention Logic', () => {
    it('should not add duplicate message IDs', () => {
      let messageIds: string[] = [];
      
      messageIds = appendMessageWithDuplicatePrevention(messageIds, 'msg-1');
      messageIds = appendMessageWithDuplicatePrevention(messageIds, 'msg-1');
      
      expect(messageIds).toEqual(['msg-1']);
      expect(messageIds).toHaveLength(1);
    });

    it('should allow different message IDs', () => {
      let messageIds: string[] = [];
      
      messageIds = appendMessageWithDuplicatePrevention(messageIds, 'msg-1');
      messageIds = appendMessageWithDuplicatePrevention(messageIds, 'msg-2');
      messageIds = appendMessageWithDuplicatePrevention(messageIds, 'msg-3');
      
      expect(messageIds).toEqual(['msg-1', 'msg-2', 'msg-3']);
      expect(messageIds).toHaveLength(3);
    });

    it('should maintain insertion order', () => {
      let messageIds: string[] = [];
      
      for (let i = 0; i < 5; i++) {
        messageIds = appendMessageWithDuplicatePrevention(messageIds, `msg-${i}`);
      }
      
      expect(messageIds).toEqual(['msg-0', 'msg-1', 'msg-2', 'msg-3', 'msg-4']);
    });
  });

  describe('Renderable Message Filtering', () => {
    it('should include user messages', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', { id: 'msg-1', role: 'user', content: 'Hello', contentChunks: ['Hello'] } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toContain('msg-1');
    });

    it('should include coordinator messages', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'coordinator',
          content: 'Coordinating',
          contentChunks: ['Coordinating'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toContain('msg-1');
    });

    it('should include planner messages', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'planner',
          content: 'Planning',
          contentChunks: ['Planning'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toContain('msg-1');
    });

    it('should include podcast messages', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'podcast',
          content: 'Podcast',
          contentChunks: ['Podcast'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toContain('msg-1');
    });

    it('should include research messages when in researchIds', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'researcher',
          content: 'Researching',
          contentChunks: ['Researching'],
        } as Message],
      ]);
      const researchIds = ['msg-1'];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toContain('msg-1');
    });

    it('should exclude researcher messages not in researchIds', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'researcher',
          content: 'Researching',
          contentChunks: ['Researching'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).not.toContain('msg-1');
    });

    it('should exclude coder messages not in researchIds', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'coder',
          content: 'Coding',
          contentChunks: ['Coding'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).not.toContain('msg-1');
    });

    it('should exclude reporter messages', () => {
      const messageIds = ['msg-1'];
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          agent: 'reporter',
          content: 'Report',
          contentChunks: ['Report'],
        } as Message],
      ]);
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).not.toContain('msg-1');
    });

    it('should handle mixed message types correctly', () => {
      const messageIds = ['msg-1', 'msg-2', 'msg-3', 'msg-4', 'msg-5'];
      const messages = new Map<string, Message>([
        ['msg-1', { id: 'msg-1', role: 'user', content: 'User', contentChunks: ['User'] } as Message],
        ['msg-2', {
          id: 'msg-2',
          role: 'assistant',
          agent: 'coordinator',
          content: 'Coordinator',
          contentChunks: ['Coordinator'],
        } as Message],
        ['msg-3', {
          id: 'msg-3',
          role: 'assistant',
          agent: 'researcher',
          content: 'Researcher',
          contentChunks: ['Researcher'],
        } as Message],
        ['msg-4', {
          id: 'msg-4',
          role: 'assistant',
          agent: 'coder',
          content: 'Coder',
          contentChunks: ['Coder'],
        } as Message],
        ['msg-5', {
          id: 'msg-5',
          role: 'assistant',
          agent: 'planner',
          content: 'Planner',
          contentChunks: ['Planner'],
        } as Message],
      ]);
      const researchIds = ['msg-3', 'msg-4'];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      // Should include: user, coordinator, planner, and research starts (researcher, coder)
      expect(renderable).toEqual(['msg-1', 'msg-2', 'msg-3', 'msg-4', 'msg-5']);
      expect(renderable).toHaveLength(5);
    });

    it('should maintain message order after filtering', () => {
      const messageIds = ['msg-1', 'msg-2', 'msg-3', 'msg-4', 'msg-5'];
      const messages = new Map<string, Message>([
        ['msg-1', { id: 'msg-1', role: 'user', content: 'User', contentChunks: ['User'] } as Message],
        ['msg-2', {
          id: 'msg-2',
          role: 'assistant',
          agent: 'researcher',
          content: 'Researcher',
          contentChunks: ['Researcher'],
        } as Message],
        ['msg-3', {
          id: 'msg-3',
          role: 'assistant',
          agent: 'planner',
          content: 'Planner',
          contentChunks: ['Planner'],
        } as Message],
        ['msg-4', {
          id: 'msg-4',
          role: 'assistant',
          agent: 'reporter',
          content: 'Reporter',
          contentChunks: ['Reporter'],
        } as Message],
        ['msg-5', {
          id: 'msg-5',
          role: 'assistant',
          agent: 'coordinator',
          content: 'Coordinator',
          contentChunks: ['Coordinator'],
        } as Message],
      ]);
      const researchIds = ['msg-2'];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      // Order should be: msg-1 (user), msg-2 (research), msg-3 (planner), msg-5 (coordinator)
      // msg-4 (reporter) should be filtered out
      expect(renderable).toEqual(['msg-1', 'msg-2', 'msg-3', 'msg-5']);
    });

    it('should handle empty messages gracefully', () => {
      const messageIds: string[] = [];
      const messages = new Map<string, Message>();
      const researchIds: string[] = [];
      
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      
      expect(renderable).toEqual([]);
      expect(renderable).toHaveLength(0);
    });
  });

  describe('Tool Call Result Handling', () => {
    it('should find message by tool call ID', () => {
      const toolCallId = 'tool-123';
      const message: Message = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Searching',
        contentChunks: ['Searching'],
        toolCalls: [
          { id: toolCallId, name: 'web_search', args: {}, result: undefined },
        ],
      } as Message;
      const messages = new Map<string, Message>([
        ['msg-1', message],
      ]);
      
      const found = findMessageByToolCallId(toolCallId, messages);
      
      expect(found).toBeDefined();
      expect(found?.id).toBe('msg-1');
      expect(found?.toolCalls?.[0]?.id).toBe(toolCallId);
    });

    it('should return undefined if tool call not found', () => {
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          content: 'Searching',
          contentChunks: ['Searching'],
          toolCalls: [
            { id: 'tool-1', name: 'web_search', args: {}, result: undefined },
          ],
        } as Message],
      ]);
      
      const found = findMessageByToolCallId('tool-999', messages);
      
      expect(found).toBeUndefined();
    });

    it('should find correct message among multiple tool calls', () => {
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'assistant',
          content: 'Searching 1',
          contentChunks: ['Searching 1'],
          toolCalls: [
            { id: 'tool-1', name: 'web_search', args: {}, result: undefined },
          ],
        } as Message],
        ['msg-2', {
          id: 'msg-2',
          role: 'assistant',
          content: 'Searching 2',
          contentChunks: ['Searching 2'],
          toolCalls: [
            { id: 'tool-2', name: 'web_search', args: {}, result: undefined },
          ],
        } as Message],
      ]);
      
      const found = findMessageByToolCallId('tool-2', messages);
      
      expect(found?.id).toBe('msg-2');
    });

    it('should handle message without tool calls', () => {
      const messages = new Map<string, Message>([
        ['msg-1', {
          id: 'msg-1',
          role: 'user',
          content: 'Hello',
          contentChunks: ['Hello'],
        } as Message],
      ]);
      
      const found = findMessageByToolCallId('tool-1', messages);
      
      expect(found).toBeUndefined();
    });

    it('should not create duplicates when processing tool call results', () => {
      const toolCallId = 'tool-1';
      let messageIds: string[] = [];
      const messages = new Map<string, Message>();
      
      // Simulate adding message with tool call
      const message: Message = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Searching',
        contentChunks: ['Searching'],
        toolCalls: [
          { id: toolCallId, name: 'web_search', args: {}, result: undefined },
        ],
      } as Message;
      
      messageIds = appendMessageWithDuplicatePrevention(messageIds, message.id);
      messages.set(message.id, message);
      
      // Simulate processing tool call result
      const foundMessage = findMessageByToolCallId(toolCallId, messages);
      if (foundMessage) {
        messageIds = appendMessageWithDuplicatePrevention(messageIds, foundMessage.id);
      }
      
      // Should still be only one message ID
      expect(messageIds).toHaveLength(1);
      expect(messageIds).toEqual(['msg-1']);
    });
  });

  describe('No Duplicate Keys Scenario', () => {
    it('should not create duplicate keys in realistic message flow', () => {
      let messageIds: string[] = [];
      const messages = new Map<string, Message>();
      const researchIds: string[] = [];
      
      // Add user message
      const userMsg: Message = {
        id: 'user-1',
        role: 'user',
        content: 'Research topic',
        contentChunks: ['Research topic'],
      } as Message;
      messageIds = appendMessageWithDuplicatePrevention(messageIds, userMsg.id);
      messages.set(userMsg.id, userMsg);
      
      // Add plan message
      const planMsg: Message = {
        id: 'plan-1',
        role: 'assistant',
        agent: 'planner',
        content: 'Research plan',
        contentChunks: ['Research plan'],
      } as Message;
      messageIds = appendMessageWithDuplicatePrevention(messageIds, planMsg.id);
      messages.set(planMsg.id, planMsg);
      
      // Add research message
      const researchMsg: Message = {
        id: 'research-1',
        role: 'assistant',
        agent: 'researcher',
        content: 'Research findings',
        contentChunks: ['Research findings'],
      } as Message;
      messageIds = appendMessageWithDuplicatePrevention(messageIds, researchMsg.id);
      messages.set(researchMsg.id, researchMsg);
      researchIds.push(researchMsg.id);
      
      // Simulate update (shouldn't add duplicate)
      messageIds = appendMessageWithDuplicatePrevention(messageIds, planMsg.id);
      
      // Verify
      expect(messageIds).toEqual(['user-1', 'plan-1', 'research-1']);
      expect(messageIds).toHaveLength(3);
      
      // Verify no duplicates
      const uniqueIds = new Set(messageIds);
      expect(messageIds.length).toBe(uniqueIds.size);
      
      // Verify filtering works
      const renderable = filterRenderableMessageIds(messageIds, messages, researchIds);
      expect(renderable).toEqual(['user-1', 'plan-1', 'research-1']);
      expect(renderable).toHaveLength(3);
    });
  });
});
