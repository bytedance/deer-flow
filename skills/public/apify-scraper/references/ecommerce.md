# E-Commerce Actors

## Actor: apify/e-commerce-scraping-tool

Generic e-commerce scraper for Amazon, eBay, Walmart, Alza and many other online shops. Returns product name, price, rating, reviews count, availability.

### Input Template — Listing or Search Results URL

```json
{
  "listingUrls": [
    {"url": "<CATEGORY_OR_SEARCH_RESULTS_URL>"}
  ],
  "maxProductResults": 10
}
```

### Input Template — Keyword Search

```json
{
  "keyword": "<PRODUCT KEYWORD>",
  "marketplaces": ["www.amazon.com"],
  "maxProductResults": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| listingUrls | array of objects | Category or search results pages that list many products |
| detailsUrls | array of objects | Individual product pages, e.g. `https://www.amazon.com/dp/B09WNK39JN/` |
| keyword | string | Product search term. Use with `marketplaces` |
| marketplaces | array of strings | Shop domains to search with `keyword`, e.g. `["www.amazon.com", "www.ebay.com"]` |
| maxProductResults | integer | Max products for the whole run |

### Examples

User: "Scrape laptop prices from Amazon"

```json
{
  "keyword": "laptop",
  "marketplaces": ["www.amazon.com"],
  "maxProductResults": 10
}
```

User: "Get the price of https://www.amazon.com/dp/B09WNK39JN/"

```json
{
  "detailsUrls": [{"url": "https://www.amazon.com/dp/B09WNK39JN/"}]
}
```

---

## Actor: voyager/booking-scraper

Scrapes Booking.com hotel listings: name, price, rating, location, amenities, availability.

### Input Template

```json
{
  "search": "<DESTINATION>",
  "checkIn": "<YYYY-MM-DD>",
  "checkOut": "<YYYY-MM-DD>",
  "adults": 2,
  "maxItems": 10
}
```

**Note:** Dates are optional but give real prices and availability; ask the user if relevant. If the user provides a Booking.com search URL copied from their browser, pass it as `"startUrls": [{"url": "..."}]` instead of `search`.

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| search | string | Destination name, e.g. `"Prague"` |
| startUrls | array of objects | Booking.com search results URLs, instead of `search` |
| checkIn / checkOut | string | `YYYY-MM-DD` |
| adults | integer | Number of adult guests (default 2) |
| maxItems | integer | Max hotels per destination or URL |
| currency | string | Optional. E.g. `"EUR"` (default `"USD"`) |

### Example

User: "Find hotels in Prague on Booking.com for June 1–7, 2027, 2 adults"

```json
{
  "search": "Prague",
  "checkIn": "2027-06-01",
  "checkOut": "2027-06-07",
  "adults": 2,
  "maxItems": 10
}
```

---

## Actor: maxcopell/tripadvisor-reviews

Scrapes reviews from TripAdvisor for restaurants, hotels, and attractions.

### Input Template

```json
{
  "startUrls": [
    {"url": "<TRIPADVISOR_LISTING_URL>"}
  ],
  "maxItemsPerQuery": 10
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| startUrls | array of objects | Direct URL to a TripAdvisor restaurant, hotel, or attraction page |
| maxItemsPerQuery | integer | Max reviews per place |
| lastReviewDate | string | Optional. Only reviews since this date, `YYYY-MM-DD` |

**Note:** A direct TripAdvisor listing URL is required. If the user gives only a name/location, use `web_search` to find the TripAdvisor page URL first (e.g. search `"Hilton New York Times Square TripAdvisor"`), then use that URL.

### Example

User: "Get 10 reviews of the Hilton New York Times Square on TripAdvisor"

```json
{
  "startUrls": [{"url": "https://www.tripadvisor.com/Hotel_Review-g60763-d208453-Reviews-Hilton_New_York_Times_Square-New_York_City_New_York.html"}],
  "maxItemsPerQuery": 10
}
```
