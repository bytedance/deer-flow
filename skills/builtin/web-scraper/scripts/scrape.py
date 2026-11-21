#!/usr/bin/env python3
"""
Web Scraper Script for DeerFlow
Extracts structured content from web pages with intelligent parsing.
"""

import argparse
import json
import sys
from datetime import datetime
from urllib.parse import urljoin, urlparse
import re

try:
    import requests
    from bs4 import BeautifulSoup
    import html2text
except ImportError:
    print("Error: Required packages not installed.", file=sys.stderr)
    print("Run: pip install requests beautifulsoup4 lxml html2text", file=sys.stderr)
    sys.exit(1)


class WebScraper:
    def __init__(self, url, timeout=30):
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'DeerFlow-WebScraper/1.0 (Research Bot; +https://github.com/bytedance/deer-flow)'
        })

    def validate_url(self):
        """Validate URL format and scheme."""
        try:
            result = urlparse(self.url)
            return all([result.scheme in ['http', 'https'], result.netloc])
        except Exception:
            return False

    def fetch_page(self):
        """Fetch the web page content."""
        try:
            response = self.session.get(self.url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()

            # Update URL if redirected
            if response.url != self.url:
                self.url = response.url

            return response.text, response.status_code
        except requests.exceptions.Timeout:
            raise Exception(f"Request timed out after {self.timeout} seconds")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch page: {str(e)}")

    def extract_metadata(self, soup):
        """Extract page metadata."""
        metadata = {}

        # Author
        author_meta = soup.find('meta', attrs={'name': 'author'}) or \
                     soup.find('meta', attrs={'property': 'article:author'})
        if author_meta:
            metadata['author'] = author_meta.get('content', '')

        # Publish date
        date_meta = soup.find('meta', attrs={'property': 'article:published_time'}) or \
                   soup.find('meta', attrs={'name': 'date'})
        if date_meta:
            metadata['publish_date'] = date_meta.get('content', '')

        # Keywords
        keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta:
            keywords_str = keywords_meta.get('content', '')
            metadata['keywords'] = [k.strip() for k in keywords_str.split(',') if k.strip()]

        return metadata

    def extract_images(self, soup):
        """Extract images with alt text."""
        images = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src:
                # Convert relative URLs to absolute
                absolute_url = urljoin(self.url, src)
                images.append({
                    'url': absolute_url,
                    'alt': img.get('alt', '')
                })
        return images

    def extract_links(self, soup):
        """Extract important links."""
        links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True)

            # Skip empty links and anchors
            if href and not href.startswith('#') and text:
                absolute_url = urljoin(self.url, href)
                links.append({
                    'text': text[:100],  # Limit text length
                    'url': absolute_url
                })

        # Limit to first 50 links to avoid bloat
        return links[:50]

    def clean_body_text(self, soup):
        """Extract and clean main body text."""
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
            element.decompose()

        # Try to find main content area
        main_content = soup.find('main') or \
                      soup.find('article') or \
                      soup.find('div', class_=re.compile(r'(content|article|post|entry)', re.I)) or \
                      soup.find('body')

        if main_content:
            # Convert to markdown for cleaner text
            h2t = html2text.HTML2Text()
            h2t.ignore_links = False
            h2t.ignore_images = True
            h2t.body_width = 0  # No wrapping

            text = h2t.handle(str(main_content))

            # Clean up excessive whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = text.strip()

            return text

        return soup.get_text(strip=True)

    def scrape(self):
        """Main scraping logic."""
        if not self.validate_url():
            return {
                'url': self.url,
                'scraped_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'error',
                'error': 'Invalid URL format'
            }

        try:
            html_content, status_code = self.fetch_page()
            soup = BeautifulSoup(html_content, 'lxml')

            # Extract title
            title = ''
            if soup.title:
                title = soup.title.string.strip()
            else:
                title_meta = soup.find('meta', attrs={'property': 'og:title'})
                if title_meta:
                    title = title_meta.get('content', '')

            # Extract description
            description = ''
            desc_meta = soup.find('meta', attrs={'name': 'description'}) or \
                       soup.find('meta', attrs={'property': 'og:description'})
            if desc_meta:
                description = desc_meta.get('content', '')

            # Extract all data
            result = {
                'url': self.url,
                'scraped_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'success',
                'status_code': status_code,
                'data': {
                    'title': title,
                    'description': description,
                    'body': self.clean_body_text(soup),
                    'images': self.extract_images(soup),
                    'links': self.extract_links(soup),
                    'metadata': self.extract_metadata(soup)
                }
            }

            return result

        except Exception as e:
            return {
                'url': self.url,
                'scraped_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'error',
                'error': str(e)
            }


def main():
    parser = argparse.ArgumentParser(description='Scrape web pages and extract structured content')
    parser.add_argument('--url', required=True, help='URL to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--timeout', type=int, default=30, help='Request timeout in seconds')

    args = parser.parse_args()

    scraper = WebScraper(args.url, timeout=args.timeout)
    result = scraper.scrape()

    # Write result to file
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary to stdout
    if result['status'] == 'success':
        print(f"✓ Successfully scraped: {result['url']}")
        print(f"  Title: {result['data']['title']}")
        print(f"  Body length: {len(result['data']['body'])} chars")
        print(f"  Images: {len(result['data']['images'])}")
        print(f"  Links: {len(result['data']['links'])}")
    else:
        print(f"✗ Failed to scrape: {result['url']}", file=sys.stderr)
        print(f"  Error: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
