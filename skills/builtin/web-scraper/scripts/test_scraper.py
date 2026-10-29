#!/usr/bin/env python3
"""
Simple test script to verify the web scraper works correctly.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrape import WebScraper

def test_scraper():
    """Test the scraper with a simple webpage."""
    print("Testing Web Scraper...")
    print("-" * 50)

    # Test URL (example.com is a simple test page)
    test_url = "https://example.com"

    print(f"Testing URL: {test_url}\n")

    scraper = WebScraper(test_url, timeout=15)
    result = scraper.scrape()

    if result['status'] == 'success':
        print("✓ Test PASSED\n")
        print(f"Title: {result['data']['title']}")
        print(f"Description: {result['data']['description'][:100]}..." if len(result['data']['description']) > 100 else f"Description: {result['data']['description']}")
        print(f"Body length: {len(result['data']['body'])} characters")
        print(f"Images found: {len(result['data']['images'])}")
        print(f"Links found: {len(result['data']['links'])}")
        print(f"\nFirst 200 chars of body:")
        print(result['data']['body'][:200])
        return True
    else:
        print("✗ Test FAILED\n")
        print(f"Error: {result.get('error', 'Unknown error')}")
        return False

if __name__ == '__main__':
    success = test_scraper()
    sys.exit(0 if success else 1)
