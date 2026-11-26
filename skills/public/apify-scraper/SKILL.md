---
name: apify-scraper
description: >-
  Use this skill to collect structured data with Apify Actors from Instagram,
  Facebook, TikTok, YouTube, Google Maps, e-commerce stores, TripAdvisor or
  Booking.com, such as profiles, posts, reels, comments, videos, places,
  products, hotels and reviews. Also use it for bulk structured extraction
  from one specific website. It needs the apify_actor_start and
  apify_actor_await tools; when they are not available, do not load it and
  use your other tools, such as web_search and web_fetch, instead. Do not use
  it for a single web search or for reading one page; use the web_search and
  web_fetch tools for those.
---

# Apify Ultimate Scraper Skill

## Core Rule

This skill needs the `apify_actor_start` and `apify_actor_await` tools. Check your tool list first. If they are not in it:

- Do the task with the other tools you have, such as `web_search`, `web_fetch` or an MCP tool, and ignore the rest of this skill. Do not read its reference files, do not call any `apify_actor_*` tool, and do not call the Apify API yourself, for example with `bash` or `curl`.
- If the user asked to use Apify or an Apify Actor, end your answer by telling them that the Apify Actor tools are not enabled, and that they can enable them in `config.yaml` (see the Apify blocks in `config.example.yaml`) and set `APIFY_API_TOKEN`.

For tasks in the routing table below, use the listed Actor ID and do not call `apify_actor_discover`.
Read the reference file to get the input template before calling `apify_actor_start`.

## Actor Routing Table

| Task | Actor ID | Reference |
|------|----------|-----------|
| Instagram profiles | apify/instagram-profile-scraper | references/instagram.md |
| Instagram posts | apify/instagram-post-scraper | references/instagram.md |
| Instagram hashtags | apify/instagram-hashtag-scraper | references/instagram.md |
| Instagram comments | apify/instagram-comment-scraper | references/instagram.md |
| Instagram reels | apify/instagram-reel-scraper | references/instagram.md |
| Google Maps listings | compass/crawler-google-places | references/google-maps.md |
| YouTube videos/channels/search | streamers/youtube-scraper | references/youtube.md |
| TikTok profiles/hashtags | clockworks/tiktok-scraper | references/tiktok.md |
| Facebook page info | apify/facebook-pages-scraper | references/facebook.md |
| Facebook page posts | apify/facebook-posts-scraper | references/facebook.md |
| E-commerce products | apify/e-commerce-scraping-tool | references/ecommerce.md |
| Booking.com hotels | voyager/booking-scraper | references/ecommerce.md |
| TripAdvisor reviews | maxcopell/tripadvisor-reviews | references/ecommerce.md |

## Workflow

1. Match the user's task to a row in the routing table.
2. Read the reference file for that Actor with `read_file`.
3. Fill the input template with values from the user's request. Keep result limits small unless the user asks for more; `apify_actor_await` returns at most 50 items by default.
4. Call `apify_actor_start(actor_id, run_input, description)`, where `run_input` is the input as a JSON string. It returns `{"action": "start", "runs": [{"runId", "actorId", "datasetId", "status"}]}` without waiting for the run.
5. Call `apify_actor_await(run_id, dataset_id, description)` with `runs[0].runId` and `runs[0].datasetId`. It waits for the run to finish and returns its results.
6. If the await result's `status` is `TIMED_OUT`, only the wait ended and the run is still going on Apify: call `apify_actor_await` again with the same IDs. Its `statusMessage` and `itemCount` show how far the run has got. For `FAILED`, `ABORTED` or `TIMED-OUT` (the run itself failed or timed out), report the error and its `statusMessage` to the user. Do not restart the run automatically.

**Several runs in parallel:** call `apify_actor_start` once per run first (for example, one run per profile), then call `apify_actor_await` for each run.

## When to Fall Back to Discovery

Only use `apify_actor_discover` when the task does not match any row above. In that case:
1. Read `references/actor-catalog.md` for the curated shortlist and pick the most specific Actor ID. If nothing there fits, call `apify_actor_discover(query="...")` to search the Apify Store.
2. Call `apify_actor_discover(actor_id="owner/name")` to get that Actor's input schema (`inputSchema`).
3. Build the input from the schema's `properties` and `required` fields, then continue with step 4 of the workflow.
