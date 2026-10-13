---
title: API rate limits
category: developer
url: https://help.nimbus.example/developers/rate-limits
---

## Limits by plan

- **Pro:** 100 requests per minute per account.
- **Enterprise:** 1,000 requests per minute per account. Higher limits are available on request.

## When you hit the limit

The API returns `429 Too Many Requests` with a `Retry-After` header giving the number of seconds to wait. Every response includes `X-RateLimit-Remaining` so you can slow down before reaching zero.

## Best practices

Retry with exponential backoff and jitter, cache responses that rarely change, and use webhooks instead of polling for updates.
