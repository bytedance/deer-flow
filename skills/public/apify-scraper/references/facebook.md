# Facebook Actors

Both Actors work only on public Facebook pages, not on personal profiles. For comments on posts, use `apify/facebook-comments-scraper` from the catalog.

## Actor: apify/facebook-pages-scraper

Scrapes page info: name, intro, categories, likes, followers, rating, address, phone, website. It takes only page URLs and returns one item per page; use `apify/facebook-posts-scraper` for posts.

### Input Template

```json
{
  "startUrls": [
    {"url": "https://www.facebook.com/<PAGE_NAME>/"}
  ]
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| startUrls | array of objects | Facebook page URLs, one `{"url": ...}` object per page |

### Example

User: "Get the contact details and follower count of the NASA Facebook page"

```json
{
  "startUrls": [{"url": "https://www.facebook.com/NASA/"}]
}
```

---

## Actor: apify/facebook-posts-scraper

Scrapes posts from Facebook pages: text, date, likes, comments count, shares, media URLs.

### Input Template

```json
{
  "startUrls": [
    {"url": "https://www.facebook.com/<PAGE_NAME>/"}
  ],
  "resultsLimit": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| startUrls | array of objects | Facebook page URLs or post URLs |
| resultsLimit | integer | Max posts per page. Ignored for post URLs |
| onlyPostsNewerThan | string | Optional. `YYYY-MM-DD` or relative, e.g. `"1 month"` |

### Example

User: "Get the 5 latest posts from the Humans of New York Facebook page"

```json
{
  "startUrls": [{"url": "https://www.facebook.com/humansofnewyork/"}],
  "resultsLimit": 5
}
```
