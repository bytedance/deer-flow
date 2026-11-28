# Instagram Actors

## Actor: apify/instagram-profile-scraper

Scrapes public profile data: bio, follower/following counts, post count, verified status. Returns one item per username.

### Input Template

```json
{
  "usernames": ["<USERNAME>"]
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| usernames | array of strings | Instagram usernames without @. E.g. `["humansofny", "nasa"]` |

### Example

User: "Get Instagram profile info for @humansofny"

```json
{
  "usernames": ["humansofny"]
}
```

---

## Actor: apify/instagram-post-scraper

Scrapes posts from profiles or single post URLs. Returns captions, likes, comments count, media URLs. For hashtags, use `apify/instagram-hashtag-scraper`.

### Input Template

```json
{
  "username": ["<USERNAME>"],
  "resultsLimit": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| username | array of strings | Usernames (without @), profile URLs, or post URLs (`https://www.instagram.com/p/<POST_ID>/`) |
| resultsLimit | integer | Max posts per profile. Ignored for post URLs |
| onlyPostsNewerThan | string | Optional. `YYYY-MM-DD` or relative, e.g. `"2 weeks"` |

### Examples

User: "Scrape the last 10 posts from @natgeo"

```json
{
  "username": ["natgeo"],
  "resultsLimit": 10
}
```

User: "Get data from this Instagram post https://www.instagram.com/p/DLNsnpUTdVS/"

```json
{
  "username": ["https://www.instagram.com/p/DLNsnpUTdVS/"]
}
```

---

## Actor: apify/instagram-hashtag-scraper

Scrapes posts or reels that use a hashtag. Returns captions, likes, comments count, owner, media URLs.

### Input Template

```json
{
  "hashtags": ["<HASHTAG>"],
  "resultsLimit": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| hashtags | array of strings | One hashtag per entry, with or without `#`. Words in one entry merge into one hashtag |
| resultsType | string | Optional. `"posts"` (default), `"reels"` or `"stories"` |
| resultsLimit | integer | Max results per hashtag |

### Example

User: "Find 10 posts tagged #artificialintelligence"

```json
{
  "hashtags": ["artificialintelligence"],
  "resultsLimit": 10
}
```

---

## Actor: apify/instagram-comment-scraper

Scrapes comments from Instagram posts and reels.

### Input Template

```json
{
  "directUrls": ["https://www.instagram.com/p/<POST_ID>/"],
  "resultsLimit": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| directUrls | array of strings | Post or reel URLs, e.g. `https://www.instagram.com/p/<POST_ID>/` or `https://www.instagram.com/reel/<REEL_ID>/` |
| resultsLimit | integer | Max comments per post |
| includeNestedComments | boolean | Optional. Also scrape replies |

### Example

User: "Get 10 comments from this Instagram post https://www.instagram.com/p/DN8-GjPkgjS/"

```json
{
  "directUrls": ["https://www.instagram.com/p/DN8-GjPkgjS/"],
  "resultsLimit": 10
}
```

---

## Actor: apify/instagram-reel-scraper

Scrapes Instagram Reels: video URL, caption, play count, like count, author.

### Input Template

```json
{
  "username": ["<USERNAME>"],
  "resultsLimit": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| username | array of strings | Usernames (without @), profile URLs, or reel URLs |
| resultsLimit | integer | Max reels per profile. Ignored for reel URLs |

### Example

User: "Get the latest reels from @natgeo"

```json
{
  "username": ["natgeo"],
  "resultsLimit": 10
}
```
