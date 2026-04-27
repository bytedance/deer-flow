# YouTube Actor

## Actor: streamers/youtube-scraper

Scrapes YouTube videos, channels, and search results. Returns title, description, view count, like count, published date, channel info.

### Input Template — Search

```json
{
  "searchKeywords": "<SEARCH QUERY>",
  "maxResults": 20
}
```

### Input Template — Specific Channel or Video

```json
{
  "startUrls": [
    {"url": "https://www.youtube.com/@<CHANNEL_HANDLE>"}
  ],
  "maxResults": 20
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| searchKeywords | string | Search query. Used when you want to search YouTube, not scrape a specific channel |
| startUrls | array of objects | Direct URLs to channels, videos, or playlists. Use instead of searchKeywords for specific targets |
| maxResults | integer | Max videos/results to return |

### Examples

User: "Find the top 10 YouTube videos about LLM benchmarking"

```json
{
  "searchKeywords": "LLM benchmarking 2025",
  "maxResults": 10
}
```

User: "Scrape the latest 20 videos from the Apify YouTube channel"

```json
{
  "startUrls": [{"url": "https://www.youtube.com/@apify"}],
  "maxResults": 20
}
```
