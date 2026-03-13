# Tech Explainer Podcast Template

Use this template when converting technical documentation, API guides, or developer tutorials into podcasts.

## Input Preparation

When the user wants to convert technical content to a podcast, help them structure the input:

1. **Simplify Code Examples**: Replace code snippets with plain language descriptions
   - Instead of showing actual code, describe what the code does
   - Focus on concepts rather than syntax

2. **Remove Complex Notation**:
   - Mathematical formulas should be explained in words
   - API endpoints described by function rather than URL paths
   - Configuration examples summarized as settings descriptions

3. **Add Context**:
   - Explain why the technology matters
   - Include real-world use cases
   - Add analogies for complex concepts

## Example Transformation

### Original Technical Content:
```markdown
# Using the API

POST /api/v1/users
{
  "name": "John",
  "email": "john@example.com"
}

Response: 201 Created
```

### Podcast-Ready Content:
```markdown
# Creating Users with the API

The user creation feature allows applications to register new users in the system.
When you want to add a new user, you send their name and email address to the server.
If everything goes well, the server confirms the user was created successfully.
This is commonly used in signup flows, admin dashboards, or when importing users from other systems.
```

## Generation Command

```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/tech-explainer-script.json \
  --output-file /mnt/user-data/outputs/tech-explainer-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/tech-explainer-transcript.md
```

## Tips for Technical Podcasts

- Keep episodes focused on one main concept
- Use analogies to explain abstract concepts
- Include practical "why this matters" context
- Avoid jargon without explanation
- Make the dialogue accessible to beginners
