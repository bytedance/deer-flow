# YouTube Actor

## Actor: streamers/youtube-scraper

Scrapes YouTube videos, channels, playlists and search results. Returns title, description, view count, like count, published date, channel info.

### Input Template — Search

```json
{
  "searchQueries": ["<SEARCH QUERY>"],
  "maxResults": 10
}
```

### Input Template — Specific Channel, Video or Playlist

```json
{
  "startUrls": [
    {"url": "https://www.youtube.com/@<CHANNEL_HANDLE>"}
  ],
  "maxResults": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| searchQueries | array of strings | Search terms, as typed into YouTube's search bar. Ignored when `startUrls` is set |
| startUrls | array of objects | Channel, video, playlist or search results URLs. Use instead of `searchQueries` for specific targets |
| maxResults | integer | Max regular videos per search term or channel |
| maxResultsShorts | integer | Optional. Max Shorts per search term or channel (default 0) |
| sortVideosBy | string | Optional, channels only. `"NEWEST"`, `"POPULAR"` or `"OLDEST"` |

### Examples

User: "Find the top 10 YouTube videos about LLM benchmarking"

```json
{
  "searchQueries": ["LLM benchmarking"],
  "maxResults": 10
}
```

User: "Scrape the latest 10 videos from the Apify YouTube channel"

```json
{
  "startUrls": [{"url": "https://www.youtube.com/@apify"}],
  "maxResults": 10
}
```
