# Worker protocol (version 2)

The native app starts the bundled Python worker and talks to it over pipes:
commands on the worker's stdin, events on its stdout. Each message is one
UTF-8 JSON object followed by `\n` (NDJSON). Stdout carries only protocol
frames; diagnostics go to stderr. The app and worker ship together, so a frame
with any other `version` is rejected rather than migrated.

Every frame is an envelope:

```json
{"version": 2, "type": "<name>", "payload": {}}
```

Events add `generation` (non-negative integer) and `track` (a track object or
`null`). Unknown types, missing fields, and invalid values reject the frame:
the worker ignores a bad command; the app treats a bad event as a broken worker.

| Limit | Value |
| --- | --- |
| Command frame | 64 KiB |
| Event frame | 8 MiB (lyric payloads are kept below 6 MiB) |
| Recording candidates | 30 |

## Shared values

**Track** identifies one recording as Music reports it. The worker rounds
`duration` to two decimals, and the app echoes the object back unchanged.

```json
{"title": "浮誇", "artist": "Eason Chan", "album": "U 87", "duration": 284.0}
```

**Generation** increases whenever the worker sees a different track or loses
Music. Anything tied to an older generation is stale on both sides.

**Request revision** (`request_id`) is assigned by the app, increasing by one
for every lyric command. The worker ignores a command whose revision is not
newer than the last one it accepted, and stamps each `lyrics`/`recordings`
event with the revision it reflects; the app displays only events for its
latest revision.

**Recording reference** is provider-qualified:
`netease:<id>`, `lrclib:<id>`, `lrcapi:<token>`, or `proofread:<asset-id>`
(tokens use `[A-Za-z0-9_-]`, at most 220 characters in total).

**Language** is `cantonese`, `hokkien`, or `original`. Events may also report
`supplied` as the effective language of a proofread resource. Song preferences
additionally accept `default`, which clears the override.

## Commands (app → worker)

| Type | Payload |
| --- | --- |
| `set_language` | `language`, `request_id` |
| `set_song_language` | `request_id`, `generation`, `track`, `song_language` |
| `retry_lyrics` | `request_id`, `generation`, `retry_artwork` (bool) |
| `list_recordings` | `request_id`, `generation` |
| `choose_recording` | `request_id`, `generation`, `recording_id`, `choice_request_id` |
| `forget_recording` | `request_id`, `generation` |
| `playback_control` | `command_id`, `generation`, `track`, `action`, `position` |
| `get_data_stats` | — |
| `clear_data` | `targets`: nonempty, distinct subset of `lyrics_cache`, `recording_choices`, `song_languages` |
| `shutdown` | — |

- Commands for another generation are ignored, except that a stale
  `set_song_language` still consumes its revision so the next update
  resynchronizes the menu.
- `choose_recording` must name a candidate from the latest `recordings` event;
  `choice_request_id` is the revision that event carried.
- `retry_lyrics` bypasses lyric caches. It also refetches artwork when
  `retry_artwork` is true or no cover is cached.
- `playback_control` `action` is `play`, `pause`, `next`, `previous`, or
  `seek`; `position` (seconds) is required for `seek` and `null` otherwise.
  `command_id` is positive and increasing. The worker never repeats or retries
  a control, runs one at a time, and answers each with `control_result`.
- `get_data_stats` and `clear_data` are not tied to a track or revision. Each is
  answered with one `data_stats` event once the storage work finishes. After the first
  `get_data_stats`, the worker also sends `data_stats` whenever saved data changes (a cached
  lookup, a saved recording choice, or a saved song language). Clearing never
  removes the lyrics on screen; clearing song languages re-resolves the current song.
- Closing stdin has the same effect as `shutdown`.

## Events (worker → app)

| Type | Payload |
| --- | --- |
| `ready` | — (sent once at startup) |
| `playback` | `snapshot`, `completed_control_id` |
| `artwork` | `image` (base64, or `null` for the placeholder) |
| `status` | `code`, `message` |
| `lyrics` | lyric update |
| `recordings` | recording update |
| `control_result` | `command_id`, `ok`, and on failure `code`, `message` |
| `data_stats` | `lyrics_entries`, `lyrics_bytes` (both `null` if unreadable), `recording_choices`, `song_languages`, `message` |

**playback** is sent every poll (0.5 s). `snapshot` has `state` (`playing`,
`paused`, `stopped`, `closed`, `fast forwarding`, `rewinding`), `title`,
`artist`, `album`, `duration`, and `position`. `track` is `null` exactly when
no track is playing (empty title, stopped, or closed). `completed_control_id`
is the highest control finished before the snapshot was sampled, so a snapshot
read while a control runs cannot confirm it.

**status** reports that Music could not be read; `track` is `null`. Code
`permission_denied` stops polling until the app restarts the worker.

**lyrics** (sent when changed):

| Field | Meaning |
| --- | --- |
| `request_id` | revision the update reflects |
| `language` | global language |
| `song_language` | song override, or `null` |
| `selected_language` | effective language, or `null` for original only |
| `reason` | `song preference`, `proofread transcription`, or `global default` |
| `status` | `loading`, `ready`, `plain`, `instrumental`, `unavailable`, `error` |
| `message` | progress or error text |
| `lyrics` | lyrics object for `ready`/`plain`/`instrumental`, otherwise `null` |
| `preference_warning` | nonempty when a song preference could not be saved |
| `selection_revision` | increases after each successful recording switch |

A lyrics object has `lines` (`text`, `time` seconds or `null`, `pronunciation`
or `null`), `source` (`"<Provider> <https URL>"`), `synced`, `instrumental`,
`recording_id` (or `null`), and `proofread` (`asset_id`, `revision`,
`language`, `attribution`, or `null`).

**recordings** (sent when changed): `request_id`, `status` (`idle`, `loading`,
`ready`, `error`), `candidates` (each `recording_id`, `title`, `artists`,
`album`, `duration`), `selected_id`, `source`, `manual`, `switching`,
`message`, and `selection_revision`.
