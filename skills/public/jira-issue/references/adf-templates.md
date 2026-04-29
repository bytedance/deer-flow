# ADF Comment Templates

Jira Cloud comments use Atlassian Document Format (ADF). Below are reusable JSON templates for common scenarios.

## Plain Reply with @Mention

Use when responding to a comment mention. Replace `{ACCOUNT_ID}` and `{DISPLAY_NAME}` with the commenter's details.

```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {
          "type": "mention",
          "attrs": {
            "id": "{ACCOUNT_ID}",
            "text": "@{DISPLAY_NAME}",
            "accessLevel": ""
          }
        },
        {
          "type": "text",
          "text": " {YOUR_REPLY_TEXT}"
        }
      ]
    }
  ]
}
```

## Task Acknowledgement

Use when claiming a ticket (Step 1 of task assignment). @Mention the reporter.

```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {
          "type": "mention",
          "attrs": {
            "id": "{REPORTER_ACCOUNT_ID}",
            "text": "@{REPORTER_DISPLAY_NAME}",
            "accessLevel": ""
          }
        },
        {
          "type": "text",
          "text": " I've picked up this task and am starting work now."
        }
      ]
    }
  ]
}
```

## PR Summary

Use when posting a summary after completing a code workflow.

```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {
          "type": "mention",
          "attrs": {
            "id": "{REPORTER_ACCOUNT_ID}",
            "text": "@{REPORTER_DISPLAY_NAME}",
            "accessLevel": ""
          }
        },
        {
          "type": "text",
          "text": " Work is complete. Here's a summary:"
        }
      ]
    },
    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [
        {
          "type": "text",
          "text": "Changes"
        }
      ]
    },
    {
      "type": "bulletList",
      "content": [
        {
          "type": "listItem",
          "content": [
            {
              "type": "paragraph",
              "content": [
                {
                  "type": "text",
                  "text": "{CHANGE_DESCRIPTION_1}"
                }
              ]
            }
          ]
        },
        {
          "type": "listItem",
          "content": [
            {
              "type": "paragraph",
              "content": [
                {
                  "type": "text",
                  "text": "{CHANGE_DESCRIPTION_2}"
                }
              ]
            }
          ]
        }
      ]
    },
    {
      "type": "heading",
      "attrs": { "level": 3 },
      "content": [
        {
          "type": "text",
          "text": "Pull Request"
        }
      ]
    },
    {
      "type": "paragraph",
      "content": [
        {
          "type": "text",
          "text": "{PR_URL}",
          "marks": [
            {
              "type": "link",
              "attrs": {
                "href": "{PR_URL}"
              }
            }
          ]
        }
      ]
    }
  ]
}
```

## Blocker Notification

Use when the agent is blocked and needs human input. Transitions the ticket to **On Hold**.

```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {
          "type": "mention",
          "attrs": {
            "id": "{REPORTER_ACCOUNT_ID}",
            "text": "@{REPORTER_DISPLAY_NAME}",
            "accessLevel": ""
          }
        },
        {
          "type": "text",
          "text": " I've encountered a blocker and need your input:"
        }
      ]
    },
    {
      "type": "panel",
      "attrs": { "panelType": "warning" },
      "content": [
        {
          "type": "paragraph",
          "content": [
            {
              "type": "text",
              "text": "{BLOCKER_DESCRIPTION}"
            }
          ]
        }
      ]
    },
    {
      "type": "paragraph",
      "content": [
        {
          "type": "text",
          "text": "Moving this ticket to On Hold until resolved."
        }
      ]
    }
  ]
}
```

## Usage

1. Copy the relevant template.
2. Replace all `{PLACEHOLDER}` values.
3. Write the JSON to a temporary file:
   ```bash
   cat > /tmp/jira-reply.json << 'EOF'
   { ... your filled template ... }
   EOF
   ```
4. Post the comment:
   ```bash
   acli jira workitem comment create --key "{ISSUE_KEY}" --body-file /tmp/jira-reply.json
   ```

## Finding Account IDs

To @mention someone, you need their Atlassian account ID:

```bash
# Search by display name or email
acli jira workitem view {ISSUE_KEY} --json | jq '.fields.reporter.accountId'
acli jira workitem view {ISSUE_KEY} --json | jq '.fields.assignee.accountId'
```
