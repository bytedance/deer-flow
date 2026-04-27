# Facebook Actor

## Actor: apify/facebook-pages-scraper

Scrapes public Facebook pages: page info, recent posts, likes, comments, reactions, contact details.

### Input Template

```json
{
  "startUrls": [
    {"url": "https://www.facebook.com/<PAGE_NAME>"}
  ],
  "maxPosts": 20
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| startUrls | array of objects | URLs of Facebook pages to scrape |
| maxPosts | integer | Max posts to scrape per page (default 20) |
| maxPostComments | integer | Max comments per post. Omit for no comments. |
| maxReviews | integer | Max reviews to scrape. Omit to skip reviews. |

### Examples

User: "Scrape the Apify Facebook page and get its latest posts"

```json
{
  "startUrls": [{"url": "https://www.facebook.com/apifytech"}],
  "maxPosts": 20
}
```

User: "Get Facebook page info and 5 posts with their comments for NASA"

```json
{
  "startUrls": [{"url": "https://www.facebook.com/NASA"}],
  "maxPosts": 5,
  "maxPostComments": 10
}
```
