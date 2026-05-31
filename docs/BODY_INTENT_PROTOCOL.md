# Body Intent Protocol

`BodyIntent` is the stable interface between an LLM/agent and the body runtime.

The LLM must not output arbitrary bone rotations or free-form action names. It must choose from a small whitelist. The runtime validates every request.

## Request

```json
{
  "action": "sit_chair",
  "expression": "smile",
  "prop": "cup",
  "gaze": "look_at_user",
  "camera": "front_medium",
  "screenshot": true
}
```

## Fields

### `action`

Required. Allowed values:

- `idle`
- `look_at_user`
- `wave`
- `sit_chair`
- `stand_up`
- `hold_cup`

### `expression`

Optional. Defaults to `neutral`.

Allowed values:

- `neutral`
- `smile`
- `surprised`

### `prop`

Optional. Defaults to `none`.

Allowed values:

- `none`
- `cup`

### `gaze`

Optional. Defaults to `none`.

Allowed values:

- `none`
- `look_at_user`

### `camera`

Optional. Defaults to `front_medium`.

Allowed values:

- `front_medium`
- `front_full`
- `close_face`

### `screenshot`

Optional boolean. Defaults to `false`.

## Response

```json
{
  "ok": true,
  "state": {
    "pose": "sitting",
    "action": "sit_chair",
    "expression": "smile",
    "holding": "cup",
    "gaze": "user",
    "camera": "front_medium",
    "is_busy": false,
    "last_action_status": "success"
  },
  "screenshot_path": "godot/outputs/screenshots/20260531_000001.png",
  "errors": []
}
```

## Validation Rules

- Unknown `action` falls back to `idle` and returns an error entry.
- Unknown optional enum values fall back to defaults and return error entries.
- Extra fields are ignored or rejected depending on runtime mode.
- Runtime actions must be deterministic enough to support logging and replay.

## Design Rule

The protocol is intentionally small. Add new actions only after they are implemented, testable, and observable in `BodyState`.
