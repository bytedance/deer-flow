# Instagram Actors

## Actor: apify/instagram-profile-scraper

Scrapes public profile data: bio, follower/following counts, post count, verified status.

### Input Template

```json
{
  "usernames": ["<USERNAME>"],
  "resultsLimit": 20
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| usernames | array of strings | Instagram usernames without @. E.g. `["apify", "nasa"]` |
| resultsLimit | integer | Max profiles to return (default 20) |

### Example

User: "Get Instagram profile info for @apify"

```json
{
  "usernames": ["apify"],
  "resultsLimit": 1
}
```

---

## Actor: apify/instagram-post-scraper

Scrapes posts from a profile, hashtag, or location. Returns captions, likes, comments count, media URLs.

### Input Template

```json
{
  "directUrls": ["https://www.instagram.com/<USERNAME>/"],
  "resultsLimit": 50
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| directUrls | array of strings | Profile URL (`/username/`), hashtag URL (`/explore/tags/ai/`), or individual post URL (`/p/ABC123/`) |
| resultsLimit | integer | Max posts to scrape |

### Examples

User: "Scrape the last 20 posts from @apify"

```json
{
  "directUrls": ["https://www.instagram.com/apify/"],
  "resultsLimit": 20
}
```

User: "Find posts tagged #artificialintelligence"

```json
{
  "directUrls": ["https://www.instagram.com/explore/tags/artificialintelligence/"],
  "resultsLimit": 30
}
```

User: "Get data from this Instagram post https://www.instagram.com/p/ABC123/"

```json
{
  "directUrls": ["https://www.instagram.com/p/ABC123/"],
  "resultsLimit": 1
}
```

---

## Actor: apify/instagram-comment-scraper

Scrapes comments from Instagram posts.

### Input Template

```json
{
  "directUrls": ["https://www.instagram.com/p/<POST_ID>/"],
  "resultsLimit": 100
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| directUrls | array of strings | Direct post URLs in format `https://www.instagram.com/p/<POST_ID>/` |
| resultsLimit | integer | Max comments to scrape |

### Example

User: "Get 50 comments from this Instagram post"

```json
{
  "directUrls": ["https://www.instagram.com/p/ABC123/"],
  "resultsLimit": 50
}
```

---

## Actor: apify/instagram-reel-scraper

Scrapes Instagram Reels: video URL, description, play count, like count, author.

### Input Template

```json
{
  "directUrls": ["https://www.instagram.com/<USERNAME>/reels/"],
  "resultsLimit": 20
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| directUrls | array of strings | Profile reels URL or individual reel URL |
| resultsLimit | integer | Max reels to scrape |

### Example

User: "Get the latest reels from @apify"

```json
{
  "directUrls": ["https://www.instagram.com/apify/reels/"],
  "resultsLimit": 20
}
```
