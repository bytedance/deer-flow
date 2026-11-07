# Example: Scrape a blog article
python scripts/scrape.py --url "https://example.com/blog/ai-article" --output "output/article.json"

# Example: Scrape with custom timeout
python scripts/scrape.py --url "https://slow-website.com" --output "output/result.json" --timeout 60

# Example output structure
# The result will be saved to the specified JSON file with this structure:
# {
#   "url": "https://example.com",
#   "scraped_at": "2026-10-18T10:30:00Z",
#   "status": "success",
#   "data": {
#     "title": "Page Title",
#     "description": "Meta description",
#     "body": "Cleaned body text in Markdown format",
#     "images": [...],
#     "links": [...],
#     "metadata": {...}
#   }
# }
