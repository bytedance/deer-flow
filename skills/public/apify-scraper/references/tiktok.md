# TikTok Actor

## Actor: clockworks/tiktok-scraper

Scrapes TikTok profiles, videos, and hashtags. Returns video descriptions, play counts, like counts, comments, author details.

### Input Template — Profiles

```json
{
  "profiles": ["<USERNAME>"],
  "resultsPerPage": 20
}
```

### Input Template — Hashtag

```json
{
  "hashtags": ["<HASHTAG>"],
  "resultsPerPage": 20
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| profiles | array of strings | TikTok usernames **without** `@`. Strip it before passing. E.g. `["tiktok", "apify"]` not `["@tiktok"]` |
| hashtags | array of strings | Hashtags **without** `#`. E.g. `["ai", "programming"]` not `["#ai"]` |
| resultsPerPage | integer | Max results to return per profile or hashtag |

### Examples

User: "Get recent videos from TikTok user @apify"

```json
{
  "profiles": ["apify"],
  "resultsPerPage": 30
}
```

User: "Scrape TikTok videos with hashtag #artificialintelligence"

```json
{
  "hashtags": ["artificialintelligence"],
  "resultsPerPage": 50
}
```
