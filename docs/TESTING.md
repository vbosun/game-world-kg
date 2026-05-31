# Testing Plan

## MVP Test Layers

### 1. Protocol Validation

Validate that example `BodyIntent` files match `protocol/body_intent.schema.json`.

Cases:

- valid `idle`
- valid `wave`
- valid `sit_chair`
- valid `hold_cup`
- invalid action falls back to `idle`
- invalid optional field falls back to default

### 2. Runtime Local Demo

Run `Main.tscn` and verify:

- body starts in idle
- wave changes arm state
- sit changes pose state
- hold_cup attaches cup
- state is printed after each action

### 3. Screenshot Test

Send an action with `screenshot: true` and verify:

- PNG file is created
- response includes `screenshot_path`
- path points to an existing file

### 4. API Test

Call:

```bash
curl -X POST http://127.0.0.1:17860/body/action \
  -H "Content-Type: application/json" \
  -d '{"action":"wave","expression":"smile","camera":"front_medium","screenshot":true}'
```

Expected response fields:

- `ok`
- `state`
- `screenshot_path`
- `errors`

### 5. Python Client Test

Run:

```bash
python client/python/test_action.py
```

Expected:

- no uncaught exception
- each command returns JSON
- screenshot commands save output

## Regression Rule

Placeholder body must remain runnable even after real GLB body support is added.

## Debug Artifacts

Runtime should eventually write:

```text
godot/outputs/screenshots/*.png
godot/outputs/logs/body_runtime.jsonl
```

Each log line should include:

- timestamp
- request intent
- normalized intent
- body state
- screenshot path
- errors
