---
title: API authentication errors (401 and 403)
category: developer
url: https://help.nimbus.example/developers/auth-errors
---

## 401 Unauthorized

The API key is missing, mistyped or revoked. Send it in the `Authorization: Bearer <key>` header. Generate a new key under **Settings → Developer → API keys**; keys are shown only once, so store them in a secrets manager.

## 403 Forbidden

The key is valid but your plan doesn't include API access. The Nimbus API is available on the **Pro** and **Enterprise** plans only. Upgrading takes effect immediately, so existing keys start working right away.

A 403 can also mean the key lacks the required scope. Read-only keys can't call endpoints that create or change data.

## Rotating keys

Create the new key, deploy it, then revoke the old one. Revoked keys stop working within one minute.
