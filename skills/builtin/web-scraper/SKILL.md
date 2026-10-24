# Web Scraper Skill

Extract structured content from web pages with intelligent parsing and cleaning.

## Metadata

```yaml
name: web-scraper
version: 1.0.0
description: Intelligently scrape and extract structured content from web pages, handling dynamic content, cleaning HTML, and extracting key information like titles, text, images, and metadata.
author: LJK-ikun
license: MIT
tags: [web, scraping, content-extraction, data]
allowed_tools:
  - bash
  - file_write
  - file_read
```

## When to Use

Use this skill when the agent needs to:
- Extract content from a specific URL
- Gather information from web pages for research or analysis
- Parse HTML to extract structured data (title, body text, images, links)
- Handle both static and JavaScript-rendered pages
- Clean and format web content for further processing

**Trigger phrases**: "scrape this website", "extract content from URL", "get information from webpage", "fetch page content"

## Workflow

### 1. Validate Input

Check that the URL is:
- Well-formed (starts with http:// or https://)
- Not pointing to obvious malicious domains
- Accessible (not behind authentication if not provided)

### 2. Choose Scraping Strategy

**For static pages** (blogs, articles, documentation):
- Use lightweight HTTP requests with `curl` or `fetch`
- Parse HTML with cheerio/BeautifulSoup-like tools

**For dynamic pages** (SPAs, JavaScript-heavy sites):
- Use headless browser approach
- Wait for content to load
- Execute JavaScript if needed

### 3. Execute Scraping

Run the scraping script with proper error handling:

```bash
cd scripts
python scrape.py --url "TARGET_URL" --output "../output/scraped_content.json"
```

Or for Node.js/TypeScript users:

```bash
cd scripts
node scrape.js --url "TARGET_URL" --output "../output/scraped_content.json"
```

### 4. Extract Structured Data

Parse the HTML and extract:
- **title**: Page title and meta title
- **description**: Meta description
- **body**: Main content text (cleaned of navigation, ads, footers)
- **images**: Array of image URLs with alt text
- **links**: Important hyperlinks
- **metadata**: Author, publish date, keywords
- **raw_html**: Original HTML (optional, for debugging)

### 5. Clean and Format

- Remove script tags, style tags, and comments
- Strip excessive whitespace
- Convert relative URLs to absolute
- Decode HTML entities
- Remove ads and navigation elements (using heuristics)

### 6. Return Results

Output structured JSON:

```json
{
  "url": "https://example.com/article",
  "scraped_at": "2026-10-18T10:30:00Z",
  "status": "success",
  "data": {
    "title": "Article Title",
    "description": "Meta description...",
    "body": "Main content text...",
    "images": [
      {"url": "https://example.com/img1.jpg", "alt": "Image description"}
    ],
    "links": [
      {"text": "Related Article", "url": "https://example.com/related"}
    ],
    "metadata": {
      "author": "John Doe",
      "publish_date": "2026-10-15",
      "keywords": ["tech", "ai"]
    }
  }
}
```

## Error Handling

- **404/5xx errors**: Return error status with message
- **Timeout**: Retry once with longer timeout, then fail gracefully
- **Parsing errors**: Return partial data with warning
- **Rate limiting**: Respect robots.txt and add delays between requests

## Best Practices

1. **Respect robots.txt**: Check and honor site's scraping policies
2. **Add User-Agent**: Identify as a research bot, not a browser
3. **Rate limit**: Don't hammer servers (1-2 requests per second max)
4. **Cache results**: Save scraped content to avoid re-fetching
5. **Handle redirects**: Follow 301/302 automatically but log final URL
6. **Timeout settings**: Set reasonable timeouts (10-30 seconds)

## Examples

### Example 1: Scrape a blog article

**User request**: "Extract the main content from https://example.com/blog/ai-trends"

**Agent action**:
1. Validate URL format
2. Run scraping script
3. Extract title, body text, and images
4. Return cleaned content as JSON

**Output**: Structured article data ready for summarization or analysis

### Example 2: Scrape multiple product pages

**User request**: "Get product information from these 5 URLs: [list]"

**Agent action**:
1. Loop through URLs with rate limiting
2. Extract product name, price, description, images for each
3. Aggregate results into a comparison table
4. Save to CSV for easy review

### Example 3: Monitor a webpage for changes

**User request**: "Check if this documentation page has been updated"

**Agent action**:
1. Scrape current version
2. Compare with previously scraped version (from memory)
3. Highlight differences
4. Notify user of changes

## Dependencies

The scraping scripts require these tools (install automatically if missing):

**Python approach**:
```bash
pip install requests beautifulsoup4 lxml html2text
```

**Node.js approach**:
```bash
npm install cheerio node-fetch html-to-text
```

**For dynamic pages (optional)**:
```bash
npm install playwright
# or
pip install playwright
playwright install chromium
```

## Limitations

- Cannot scrape content behind login walls (without credentials)
- May not work on sites with aggressive anti-bot measures
- JavaScript-heavy SPAs require headless browser (slower)
- Some sites may block automated access
- Respects robots.txt and may skip disallowed URLs

## Notes

- This skill prioritizes accuracy over speed
- For large-scale scraping (>100 pages), consider using batch processing
- Always check website's terms of service before scraping
- Consider using official APIs if available instead of scraping
