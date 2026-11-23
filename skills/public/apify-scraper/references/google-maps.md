# Google Maps Actor

## Actor: compass/crawler-google-places

Scrapes business listings from Google Maps: name, address, rating, reviews count, phone, website, opening hours, coordinates.

### Input Template

```json
{
  "searchStringsArray": ["<SEARCH QUERY>"],
  "maxCrawledPlacesPerSearch": 10,
  "language": "en"
}
```

Include `locationQuery` when the search term alone is ambiguous (e.g. "coffee shops" without a city):

```json
{
  "searchStringsArray": ["coffee shops"],
  "locationQuery": "Prague, Czech Republic",
  "maxCrawledPlacesPerSearch": 10,
  "language": "en"
}
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| searchStringsArray | array of strings | Search queries, same as typing into Google Maps. E.g. `["coffee shops Prague"]` |
| maxCrawledPlacesPerSearch | integer | Max places per search term |
| language | string | Results language code. E.g. `"en"`, `"cs"`, `"de"` |
| locationQuery | string | Optional. One location per run to center the search on. Use when the query has no location. E.g. `"Prague, Czech Republic"` |
| maxReviews | integer | Optional. Reviews per place (default 0, charged extra) |

### Examples

User: "Find coffee shops in Prague city centre"

```json
{
  "searchStringsArray": ["coffee shops Prague city centre"],
  "maxCrawledPlacesPerSearch": 10,
  "language": "en"
}
```

User: "Get 10 Italian restaurants in Berlin with their ratings"

```json
{
  "searchStringsArray": ["Italian restaurants"],
  "locationQuery": "Berlin, Germany",
  "maxCrawledPlacesPerSearch": 10,
  "language": "en"
}
```
