# Multi-profile settings

Server-side settings storage in SQLite. Multiple named profiles instead of a single browser-localStorage blob, so you can keep separate setups for e.g. "0DTE SPX", "AAPL swing", and "default".

## How to use

The header has a profile selector between the expiry dropdown and the **💾 Save** / **📂 Load** buttons.

| Control | Action |
|---|---|
| **dropdown** | Select an existing profile. Changing it auto-loads that profile's settings. |
| **💾 Save** | Persist current settings to the selected profile. |
| **📂 Load** | Reload the selected profile's settings (in case you've drifted). |
| **＋** | Prompt for a new profile name and save the current settings under it. |
| **🗑** | Delete the selected profile (cannot delete `default`). |

Profile names allow alphanumeric + dashes, underscores, spaces, up to 64 chars.

## Back-compat with `settings.json`

The legacy file `settings.json` (used by the original dashboard) still works as the **`default` profile**. The first save also mirrors there for any external tooling that reads the file.

## API

```
GET  /load_settings?profile=NAME    load a profile
POST /save_settings?profile=NAME    persist (creates if missing)
GET  /profiles                      list of {name, updated_at}
DELETE /profiles/<name>             delete (URL-encode the name)
```

The settings payload is a free-form JSON blob — same shape the dashboard already builds in `gatherSettings()`. Server doesn't validate the contents; clients are free to add/remove fields.

## Tables

`user_settings(profile_name PRIMARY KEY, payload_json, updated_at)`.
