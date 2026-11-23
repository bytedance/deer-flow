# TikTok Actor

## Actor: clockworks/tiktok-scraper

Scrapes TikTok profiles, videos, and hashtags. Returns video descriptions, play counts, like counts, comments, author details.

### Input Template — Profiles

```json
{
  "profiles": ["<USERNAME>"],
  "resultsPerPage": 10
}
```

### Input Template — Hashtag

```json
{
  "hashtags": ["<HASHTAG>"],
  "resultsPerPage": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| profiles | array of strings | TikTok usernames **without** `@`. Strip it before passing. E.g. `["tiktok", "apify"]` not `["@tiktok"]` |
| hashtags | array of strings | Hashtags **without** `#`. E.g. `["ai", "programming"]` not `["#ai"]` |
| searchQueries | array of strings | Optional. Keyword search across videos and profiles |
| postURLs | array of strings | Optional. Direct URLs of specific TikTok videos |
| resultsPerPage | integer | Max videos per profile, hashtag or search query (default 1) |

### Examples

User: "Get recent videos from TikTok user @apify"

```json
{
  "profiles": ["apify"],
  "resultsPerPage": 10
}
```

User: "Scrape TikTok videos with hashtag #artificialintelligence"

```json
{
  "hashtags": ["artificialintelligence"],
  "resultsPerPage": 10
}
```
