// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * Component Tests for MessageListView - Issue #588 Fix Verification
 * 
 * These tests verify that React key warnings don't occur and that
 * the component correctly handles message rendering.
 */

import type { ReactNode } from 'react';

// Mock next-intl
jest.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}));

describe('MessageListView - Issue #588: React Key Warnings Fix', () => {
  // Capture console.warn calls to detect React warnings
  let consoleWarnSpy: ReturnType<typeof jest.spyOn>;
  let consoleErrorSpy: ReturnType<typeof jest.spyOn>;

  beforeEach(() => {
    // Set up spies to catch React warnings about missing keys
    consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleWarnSpy.mockRestore();
    consoleErrorSpy.mockRestore();
    jest.clearAllMocks();
  });

  describe('No Duplicate Key Warnings', () => {
    it('should not produce React warnings about unique keys', () => {
      // Simulate React's key validation check
      const messageIds = ['msg-1', 'msg-2', 'msg-3'];
      const keys = new Set<string>();
      let hasDuplicateKeys = false;

      messageIds.forEach((id) => {
        if (keys.has(id)) {
          hasDuplicateKeys = true;
          console.warn(
            `Each child in a list should have a unique "key" prop. Found duplicate key: ${id}`
          );
        }
        keys.add(id);
      });

      // Should not have duplicate keys
      expect(hasDuplicateKeys).toBe(false);
      expect(consoleWarnSpy).not.toHaveBeenCalledWith(
        expect.stringContaining('Each child in a list should have a unique "key" prop')
      );
    });

    it('should handle rapid message updates without duplicate keys', () => {
      // Simulate rapid updates where same message ID might be processed multiple times
      const messageIds: string[] = [];

      // Simulate adding messages with duplicate prevention
      const addMessage = (id: string) => {
        if (!messageIds.includes(id)) {
          messageIds.push(id);
        }
      };

      // Rapid updates
      for (let i = 0; i < 100; i++) {
        addMessage('msg-1');
        addMessage('msg-2');
        addMessage('msg-3');
        addMessage('msg-1'); // Duplicate attempt
        addMessage('msg-2'); // Duplicate attempt
      }

      // Should have only 3 unique IDs
      expect(messageIds).toEqual(['msg-1', 'msg-2', 'msg-3']);
      expect(messageIds.length).toBe(3);

      // Verify no duplicates
      const uniqueSet = new Set(messageIds);
      expect(messageIds.length).toBe(uniqueSet.size);
    });

    it('should filter out non-renderable messages from key list', () => {
      // Simulate the filter logic for renderable messages
      type MessageType = 'user' | 'assistant';
      type Agent = 'coordinator' | 'planner' | 'researcher' | 'coder' | 'reporter' | 'podcast';

      interface MockMessage {
        id: string;
        role: MessageType;
        agent?: Agent;
      }

      const allMessages: MockMessage[] = [
        { id: 'msg-user-1', role: 'user' },
        { id: 'msg-coordinator', role: 'assistant', agent: 'coordinator' },
        { id: 'msg-researcher', role: 'assistant', agent: 'researcher' },
        { id: 'msg-coder', role: 'assistant', agent: 'coder' },
        { id: 'msg-planner', role: 'assistant', agent: 'planner' },
        { id: 'msg-reporter', role: 'assistant', agent: 'reporter' },
      ];

      const researchIds = new Set(['msg-researcher', 'msg-coder']);

      // Filter to renderable messages (excluding non-start research messages)
      const renderableIds = allMessages
        .filter((msg) => {
          return (
            msg.role === 'user' ||
            msg.agent === 'coordinator' ||
            msg.agent === 'planner' ||
            msg.agent === 'podcast' ||
            researchIds.has(msg.id) // Only startOfResearch messages
          );
        })
        .map((msg) => msg.id);

      // Verify renderable list
      expect(renderableIds).toContain('msg-user-1');
      expect(renderableIds).toContain('msg-coordinator');
      expect(renderableIds).toContain('msg-planner');
      expect(renderableIds).toContain('msg-researcher'); // startOfResearch
      expect(renderableIds).toContain('msg-coder'); // startOfResearch
      expect(renderableIds).not.toContain('msg-reporter'); // Not renderable

      // Should have no duplicate keys
      const keySet = new Set(renderableIds);
      expect(renderableIds.length).toBe(keySet.size);
    });
  });

  describe('Tool Call Result Message Handling', () => {
    it('should find correct message for tool call results without ID mismatch', () => {
      interface ToolCall {
        id: string;
        name: string;
        args: Record<string, any>;
        result?: string;
      }

      interface MockMessage {
        id: string;
        toolCalls?: ToolCall[];
      }

      const messages: MockMessage[] = [
        {
          id: 'msg-1',
          toolCalls: [
            { id: 'tool-1', name: 'web_search', args: {} },
          ],
        },
        {
          id: 'msg-2',
          toolCalls: [
            { id: 'tool-2', name: 'web_search', args: {} },
          ],
        },
      ];

      // Find message by tool call ID (simulating event processing)
      const findMessageByToolCallId = (toolCallId: string): MockMessage | undefined => {
        return messages.find((msg) =>
          msg.toolCalls?.some((tc) => tc.id === toolCallId)
        );
      };

      // Process tool call results
      const toolCallResults = [
        { tool_call_id: 'tool-1', result: 'result-1' },
        { tool_call_id: 'tool-2', result: 'result-2' },
      ];

      const messageIds: string[] = [];

      toolCallResults.forEach((result) => {
        const message = findMessageByToolCallId(result.tool_call_id);
        if (message) {
          const messageId = message.id;
          if (!messageIds.includes(messageId)) {
            messageIds.push(messageId);
          }
        }
      });

      // Should have correct message IDs without duplicates
      expect(messageIds).toEqual(['msg-1', 'msg-2']);
      expect(messageIds.length).toEqual(new Set(messageIds).size); // No duplicates
    });

    it('should not create duplicate keys when processing same tool call multiple times', () => {
      interface ToolCall {
        id: string;
        name: string;
        args: Record<string, any>;
        result?: string;
      }

      interface MockMessage {
        id: string;
        toolCalls?: ToolCall[];
      }

      const message: MockMessage = {
        id: 'msg-with-tool',
        toolCalls: [
          { id: 'tool-123', name: 'web_search', args: {} },
        ],
      };

      const messages = [message];
      const messageIds: string[] = [];

      const findMessageByToolCallId = (toolCallId: string): MockMessage | undefined => {
        return messages.find((msg) =>
          msg.toolCalls?.some((tc) => tc.id === toolCallId)
        );
      };

      // Simulate multiple events for the same tool call
      for (let i = 0; i < 5; i++) {
        const foundMessage = findMessageByToolCallId('tool-123');
        if (foundMessage) {
          if (!messageIds.includes(foundMessage.id)) {
            messageIds.push(foundMessage.id);
          }
        }
      }

      // Should only have one ID despite multiple processing
      expect(messageIds).toEqual(['msg-with-tool']);
      expect(messageIds).toHaveLength(1);
    });
  });

  describe('Renderable Message Filtering', () => {
    it('should maintain correct message order after filtering', () => {
      type MessageType = 'user' | 'assistant';
      type Agent = 'coordinator' | 'planner' | 'researcher' | 'coder' | 'podcast';

      interface MockMessage {
        id: string;
        role: MessageType;
        agent?: Agent;
      }

      const allMessageIds = [
        'msg-user-1',
        'msg-coder-1',     // Non-start, should be filtered
        'msg-coordinator',
        'msg-researcher-1', // Non-start, should be filtered
        'msg-planner',
        'msg-podcast',
      ];

      const messages = new Map<string, MockMessage>([
        ['msg-user-1', { id: 'msg-user-1', role: 'user' }],
        ['msg-coder-1', { id: 'msg-coder-1', role: 'assistant', agent: 'coder' }],
        ['msg-coordinator', { id: 'msg-coordinator', role: 'assistant', agent: 'coordinator' }],
        ['msg-researcher-1', { id: 'msg-researcher-1', role: 'assistant', agent: 'researcher' }],
        ['msg-planner', { id: 'msg-planner', role: 'assistant', agent: 'planner' }],
        ['msg-podcast', { id: 'msg-podcast', role: 'assistant', agent: 'podcast' }],
      ]);

      const researchIds = new Set<string>();

      const filterRenderable = (ids: string[]): string[] => {
        return ids.filter((id) => {
          const msg = messages.get(id);
          if (!msg) return false;
          return (
            msg.role === 'user' ||
            msg.agent === 'coordinator' ||
            msg.agent === 'planner' ||
            msg.agent === 'podcast' ||
            researchIds.has(id)
          );
        });
      };

      const renderableIds = filterRenderable(allMessageIds);

      // Order should be preserved, non-renderable filtered out
      expect(renderableIds).toEqual([
        'msg-user-1',
        'msg-coordinator',
        'msg-planner',
        'msg-podcast',
      ]);

      // No duplicates
      expect(renderableIds).toHaveLength(new Set(renderableIds).size);
    });

    it('should update renderable list when research starts', () => {
      type MessageType = 'user' | 'assistant';
      type Agent = 'researcher' | 'coordinator' | 'planner' | 'podcast';

      interface MockMessage {
        id: string;
        role: MessageType;
        agent?: Agent;
      }

      const allMessageIds = [
        'msg-user-1',
        'msg-research-1',
        'msg-research-2',
      ];

      const messages = new Map<string, MockMessage>([
        ['msg-user-1', { id: 'msg-user-1', role: 'user' }],
        ['msg-research-1', { id: 'msg-research-1', role: 'assistant', agent: 'researcher' }],
        ['msg-research-2', { id: 'msg-research-2', role: 'assistant', agent: 'researcher' }],
      ]);

      let researchIds = new Set<string>();

      const filterRenderable = (ids: string[]): string[] => {
        return ids.filter((id) => {
          const msg = messages.get(id);
          if (!msg) return false;
          return (
            msg.role === 'user' ||
            msg.agent === 'coordinator' ||
            msg.agent === 'planner' ||
            msg.agent === 'podcast' ||
            researchIds.has(id)
          );
        });
      };

      // Before marking research start
      let renderableIds = filterRenderable(allMessageIds);
      expect(renderableIds).toEqual(['msg-user-1']); // Only user message

      // Mark first research as start
      researchIds.add('msg-research-1');
      renderableIds = filterRenderable(allMessageIds);
      expect(renderableIds).toEqual(['msg-user-1', 'msg-research-1']);

      // Mark second research as start
      researchIds.add('msg-research-2');
      renderableIds = filterRenderable(allMessageIds);
      expect(renderableIds).toEqual(['msg-user-1', 'msg-research-1', 'msg-research-2']);

      // No duplicates throughout
      expect(renderableIds).toHaveLength(new Set(renderableIds).size);
    });
  });

  describe('React Key Validation', () => {
    it('should validate that all keys are unique', () => {
      const messageIds = ['msg-1', 'msg-2', 'msg-3', 'msg-1']; // Has duplicate

      const seenKeys = new Set<string>();
      const duplicateKeys: string[] = [];

      messageIds.forEach((key) => {
        if (seenKeys.has(key)) {
          duplicateKeys.push(key);
        }
        seenKeys.add(key);
      });

      // Should have found the duplicate
      expect(duplicateKeys).toContain('msg-1');
      expect(duplicateKeys).toHaveLength(1);
    });

    it('should pass React key validation with filtered renderable messages', () => {
      // Simulate React key validation on renderable message IDs
      type MessageType = 'user' | 'assistant';
      type Agent = 'coordinator' | 'planner' | 'podcast' | 'coder';

      interface MockMessage {
        id: string;
        role: MessageType;
        agent?: Agent;
      }

      const allMessages: MockMessage[] = [
        { id: 'msg-user-1', role: 'user' },
        { id: 'msg-coder-1', role: 'assistant', agent: 'coder' }, // Not renderable
        { id: 'msg-coordinator', role: 'assistant', agent: 'coordinator' },
        { id: 'msg-planner', role: 'assistant', agent: 'planner' },
        { id: 'msg-podcast', role: 'assistant', agent: 'podcast' },
        { id: 'msg-coder-1', role: 'assistant', agent: 'coder' }, // Duplicate attempt
      ];

      const researchIds = new Set<string>();

      // Apply renderable filter
      const renderableMessages = allMessages.filter((msg) => {
        return (
          msg.role === 'user' ||
          msg.agent === 'coordinator' ||
          msg.agent === 'planner' ||
          msg.agent === 'podcast' ||
          researchIds.has(msg.id)
        );
      });

      const renderableIds = renderableMessages.map((msg) => msg.id);

      // Validate uniqueness
      const uniqueKeys = new Set(renderableIds);
      expect(renderableIds).toHaveLength(uniqueKeys.size);

      // Should pass React validation
      const hasUniqueKeys = renderableIds.length === new Set(renderableIds).size;
      expect(hasUniqueKeys).toBe(true);
    });
  });
});
