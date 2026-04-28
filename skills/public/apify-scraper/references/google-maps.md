# Google Maps Actor

## Actor: compass/crawler-google-places

Scrapes business listings from Google Maps: name, address, rating, reviews count, phone, website, opening hours, coordinates.

### Input Template

```json
{
  "searchStringsArray": ["<SEARCH QUERY>"],
  "maxCrawledPlacesPerSearch": 20,
  "language": "en"
}
```

Include `locationQuery` when the search term alone is ambiguous (e.g. "coffee shops" without a city):

```json
{
  "searchStringsArray": ["coffee shops"],
  "locationQuery": "Prague, Czech Republic",
  "maxCrawledPlacesPerSearch": 20,
  "language": "en"
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| searchStringsArray | array of strings | Search queries, same as typing into Google Maps. E.g. `["coffee shops Prague"]` |
| maxCrawledPlacesPerSearch | integer | Max results per query (default 20, max ~120) |
| language | string | Results language code. E.g. `"en"`, `"cs"`, `"de"` |
| locationQuery | string | Optional — center the search on a specific location. Use when the query doesn't contain a location. E.g. `"Prague, Czech Republic"` |

### Examples

User: "Find coffee shops in Prague city centre"

```json
{
  "searchStringsArray": ["coffee shops Prague city centre"],
  "maxCrawledPlacesPerSearch": 20,
  "language": "en"
}
```

User: "Get all Italian restaurants in Berlin with their ratings"

```json
{
  "searchStringsArray": ["Italian restaurants Berlin"],
  "maxCrawledPlacesPerSearch": 40,
  "language": "en"
}
```
