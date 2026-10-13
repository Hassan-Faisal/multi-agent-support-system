---
title: Changes aren't syncing between devices
category: technical
url: https://help.nimbus.example/troubleshooting/sync
---

## Check the basics

- Both devices must be signed in to the same Nimbus account. Check the email under **Settings → Account** on each device.
- Both devices need an internet connection. Changes made offline sync once you reconnect.
- Large libraries can take up to 10 minutes to finish syncing after a big change.

## Restart sync

Turn **Settings → Sync** off, wait 10 seconds, and turn it back on. This forces a full sync and resolves most stuck states.

## Conflicts

If the same item was edited on two devices while offline, Nimbus keeps both versions and marks one as "conflicted copy" so nothing is lost. Merge them by hand and delete the copy you don't need.

## Sync limits by plan

Basic includes sync across 2 devices. Pro and Enterprise include unlimited devices. If you add a third device on Basic, sync pauses on the newest device.
