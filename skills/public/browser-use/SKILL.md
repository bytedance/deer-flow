---
name: browser-use
description: Use this skill when you need to interact with a website that requires JavaScript rendering, user interaction (clicks, form fills), or login. Trigger on tasks like "go to X and do Y", "fill out the form at", "click on", "log in to", or when web_fetch returns empty/incomplete content from a dynamic page.
---

# Browser Use Skill

## Overview

This skill enables you to control a real Chromium browser to complete web tasks that cannot be done with simple HTTP requests. Use it when web pages require JavaScript, user interaction, or authentication.

## When to Use This Skill (vs web_fetch)

| Situation | Use |
|-----------|-----|
| Static HTML page, blog, docs | `web_fetch` (faster, cheaper) |
| JavaScript SPA (React/Vue/Angular) | `browser_use` |
| Need to click buttons or fill forms | `browser_use` |
| Login required before accessing content | `browser_use` |
| Page returns empty with web_fetch | `browser_use` |
| Extract data from a table that loads dynamically | `browser_use` |

## How to Use the Tool

Call `browser_use` with a clear, step-by-step natural language task:

```
browser_use(task="Go to https://example.com/pricing, find all pricing plans, and return their names and monthly prices as a list")
```

```
browser_use(task="Navigate to https://app.example.com/login, log in with username 'user@example.com' and password from environment, then go to the dashboard and extract all active projects")
```

## Writing Effective Tasks

### Be Specific About the Goal

```
❌ "Check example.com"
✅ "Go to example.com/products, find all products in the 'Software' category, and return their names, prices, and descriptions"
```

### Include the Full URL

```
❌ "Search Google for AI news"
✅ "Go to https://news.google.com, search for 'artificial intelligence', and return the top 5 headlines with their source and date"
```

### Specify What to Return

```
❌ "Look at the pricing page"
✅ "Go to https://example.com/pricing and return the exact price for the 'Pro' plan including any annual discount"
```

### Break Complex Flows Into Steps

```
✅ "1. Go to https://example.com/login
    2. Enter email 'test@example.com' in the email field
    3. Enter 'password123' in the password field
    4. Click the Login button
    5. Once on the dashboard, extract the list of all projects shown"
```

## Limitations

- Slower than `web_fetch` (launches a full browser, typically 10-60 seconds)
- Cannot access sites that require CAPTCHA solving
- Cannot handle 2FA/MFA without user interaction
- One browser session per tool call — for multi-step workflows across pages, describe the full flow in a single task description
- Requires `browser-use` and Playwright to be installed in the environment

## Common Use Cases

### Extract from Dynamic Pages
```
browser_use(task="Go to https://app.example.com/dashboard and extract all the statistics shown in the main metrics section")
```

### Web Form Submission
```
browser_use(task="Go to https://example.com/contact, fill in Name='Test User', Email='test@test.com', Message='Hello', and submit the form. Return the confirmation message shown after submission.")
```

### Authenticated Data Extraction
```
browser_use(task="Go to https://portal.example.com, log in with the provided credentials, navigate to Reports > Monthly, and download or extract the data from the current month's report table")
```

### Compare Prices Across Sites
```
browser_use(task="Go to https://site1.com/product/xyz and get the price, then go to https://site2.com/product/xyz and get the price. Return both prices for comparison.")
```
