---
id: webhook-custom-path
order: 20
---

### Optional webhook custom path

A webhook trigger may include an optional `custom_path`, which names its public URL. Without one the trigger answers at `/i/<trigger-id>`. With one it also answers at `/i/<project-id>/<custom_path>`, which lets someone know the URL before the workflow is deployed.

Rules for the value, all enforced by the server:
- Lowercase letters, digits, hyphens and underscores only. No slashes, no spaces, no uppercase.
- 255 characters or fewer, and at least one character.
- It cannot be a UUID. UUID-shaped paths resolve against trigger ids instead, so one would be unreachable.

If `custom_path` is present, preserve it EXACTLY. Do not add one proactively, and do not invent a value: the name must be unique across the whole project, and you cannot see the project's other workflows to check. Set or change it only when the user asks for a specific path.

Removing the key does not clear a saved path. To actually remove one, set `custom_path: null`, and say so, because anything already posting to that URL stops working.

Only webhook triggers take a `custom_path`. A cron trigger must not have one, and switching a webhook to cron drops it — warn the user first.
