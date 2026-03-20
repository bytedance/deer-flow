---
description: Generate a response to a common legal inquiry using configured templates
argument-hint: "[inquiry-type]"
---

# /respond -- Generate Response from Templates

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Generate a response to a common legal inquiry using configured templates. Customizes the response with specific details and includes escalation triggers for situations that should not use a templated response.

**Important**: This command assists with legal workflows but does not provide legal advice. Generated responses should be reviewed by qualified legal professionals before being sent.

## Invocation

```
/respond [inquiry-type]
```

Common inquiry types:
- `dsr` or `data-subject-request` -- Data subject access/deletion/correction requests
- `hold` or `discovery-hold` -- Litigation hold notices
- `vendor` or `vendor-question` -- Vendor legal questions
- `nda` or `nda-request` -- NDA requests from business teams
- `privacy` or `privacy-inquiry` -- Privacy-related questions
- `subpoena` -- Subpoena or legal process responses
- `insurance` -- Insurance claim notifications
- `custom` -- Use a custom template

If no inquiry type is provided, ask the user what type of response they need and show available categories.

## Workflow

### Step 1: Identify Inquiry Type

Accept the inquiry type from the user. If the type is ambiguous, show available categories and ask for clarification.

### Step 2: Load Template

Look for templates in local settings (e.g., `legal.local.md` or a templates directory).

**If templates are configured:**
- Load the appropriate template for the inquiry type
- Identify required variables (recipient name, dates, specific details)

**If no templates are configured:**
- Inform the user that no templates were found for this inquiry type
- Offer to help create a template (see Step 6)
- Provide a reasonable default response structure based on the inquiry type

### Step 3: Check Escalation Triggers

Before generating the response, evaluate whether this situation has characteristics that should NOT use a templated response:

#### Data Subject Request Escalation Triggers
- Request involves a minor's data
- Request is from a regulatory authority (not an individual)
- Request involves data that is subject to a litigation hold
- Requester is a current or former employee with an active dispute
- Request scope is unusually broad or appears to be a fishing expedition
- Request involves data processed in a jurisdiction with unique requirements

#### Discovery Hold Escalation Triggers
- The matter involves potential criminal liability
- The preservation scope is unclear or potentially overbroad
- There are questions about whether certain data is within scope
- Prior holds for the same or related matter exist
- The hold may affect ongoing business operations significantly

#### Vendor Question Escalation Triggers
- The question involves a dispute or potential breach
- The vendor is threatening litigation or termination
- The question involves regulatory compliance (not just contract terms)
- The response could create a binding commitment or waiver

#### NDA Request Escalation Triggers
- The counterparty is a competitor
- The NDA involves government classified information
- The business context suggests the NDA is for a potential M&A transaction
- The request involves unusual subject matter (AI training data, biometric data, etc.)

**If an escalation trigger is detected:**
- Alert the user that this situation may not be appropriate for a templated response
- Explain which trigger was detected and why it matters
- Recommend the user consult with a senior team member or outside counsel
- Offer to draft a preliminary response for counsel review rather than a final response

### Step 4: Gather Specific Details

Prompt the user for the details needed to customize the response:

**Data Subject Request:**
- Requester name and contact information
- Type of request (access, deletion, correction, portability, opt-out)
- What data is involved
- Applicable regulation (GDPR, CCPA, CPRA, other)
- Response deadline

**Discovery Hold:**
- Matter name and reference number
- Custodians (who needs to preserve)
- Scope of preservation (date range, data types, systems)
- Outside counsel contact
- Effective date

**Vendor Question:**
- Vendor name
- Reference agreement (if applicable)
- Specific question being addressed
- Relevant contract provisions

**NDA Request:**
- Requesting business team and contact
- Counterparty name
- Purpose of the NDA
- Mutual or unilateral
- Any special requirements

### Step 5: Generate Response

Populate the template with the gathered details. Ensure the response:
- Uses appropriate tone (professional, clear, not overly legalistic for business audiences)
- Includes all required legal elements for the response type
- References specific dates, deadlines, and obligations
- Provides clear next steps for the recipient
- Includes appropriate disclaimers or caveats

Present the draft response to the user for review before sending.

### Step 6: Template Creation (If No Template Exists)

If the user wants to create a new template:

1. Ask what type of inquiry the template is for
2. Ask for key elements that should be included
3. Ask for tone and audience (internal vs. external, business vs. legal)
4. Draft a template with variable placeholders (e.g., `{{requester_name}}`, `{{deadline}}`, `{{matter_reference}}`)
5. Include escalation triggers appropriate for the category
6. Present the template for review
7. Suggest the user save the approved template to their local settings for future use

#### Template Format

```markdown
## Template: [Category Name]

### Escalation Triggers
- [Trigger 1]
- [Trigger 2]

### Variables
- {{variable_1}}: [description]
- {{variable_2}}: [description]

### Subject Line
[Subject template]

### Body
[Response body with {{variables}}]

### Attachments
[Any standard attachments to include]

### Follow-Up
[Standard follow-up actions after sending]
```

## Output Format

```
## Generated Response: [Inquiry Type]

**To**: [recipient]
**Subject**: [subject line]

---

[Response body]

---

### Escalation Check
[Confirmation that no escalation triggers were detected, OR flagged triggers with recommendations]

### Follow-Up Actions
1. [Post-send actions]
2. [Calendar reminders to set]
3. [Tracking or logging requirements]
```

## Notes

- Always present the draft response for user review before suggesting it be sent
- If connected to email via MCP, offer to create a draft email with the response
- Track response deadlines and offer to set calendar reminders
- For regulated responses (DSRs, subpoenas), always note the applicable deadline and regulatory requirements
- Templates should be living documents; suggest updates when the user modifies a templated response, so the template can be improved over time
