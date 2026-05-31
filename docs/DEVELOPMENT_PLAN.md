# Development Plan

This plan is designed for staged implementation by Codex or another coding agent. Each stage should be committed separately.

## Stage 1: Documentation and Protocol

Create:

- `README.md`
- `docs/MVP.md`
- `docs/BODY_INTENT_PROTOCOL.md`
- `protocol/body_intent.schema.json`
- `protocol/body_state.schema.json`
- `protocol/examples/*.json`

Acceptance:

- The runtime scope is clear.
- The protocol is strict and finite.
- Example commands are present.

Commit message:

```text
docs: define AI body runtime MVP and protocol
```

## Stage 2: Godot Project Skeleton

Create:

- `godot/project.godot`
- `godot/scenes/Main.tscn`
- `godot/scenes/TestRoom.tscn`
- `godot/scenes/BodyRuntime.tscn`
- `godot/scenes/PlaceholderBody.tscn`
- controller scripts under `godot/scripts/`

Acceptance:

- Godot 4.x can open the project.
- `Main.tscn` can run.
- A test room, placeholder body, chair, cup, user anchor, and cameras exist.

Commit message:

```text
feat: bootstrap Godot body runtime scene
```

## Stage 3: Local Body Runtime Demo

Implement local action execution before HTTP.

Actions:

- `idle`
- `look_at_user`
- `wave`
- `sit_chair`
- `stand_up`
- `hold_cup`

Acceptance:

- `Main.tscn` runs a demo sequence.
- Console prints a `BodyState` after each action.
- Placeholder body visibly changes state.

Commit message:

```text
feat: implement local body runtime actions
```

## Stage 4: Camera and Screenshot

Implement:

- camera switching
- viewport screenshot capture
- screenshot path returned in state

Acceptance:

- Calling an action with `screenshot: true` writes a PNG under `godot/outputs/screenshots/`.

Commit message:

```text
feat: add camera switching and screenshot capture
```

## Stage 5: Local Control API

Implement:

- `POST /body/action`
- JSON parsing
- protocol validation
- action execution
- JSON response

Acceptance:

```bash
curl -X POST http://127.0.0.1:17860/body/action \
  -H "Content-Type: application/json" \
  -d '{"action":"wave","expression":"smile","camera":"front_medium","screenshot":true}'
```

returns `ok`, `state`, `screenshot_path`, and `errors`.

Commit message:

```text
feat: expose body action HTTP API
```

## Stage 6: Python Client

Create:

- `client/python/body_client.py`
- `client/python/test_action.py`
- curl examples

Acceptance:

```bash
python client/python/test_action.py
```

runs `idle`, `wave`, `sit_chair`, and `hold_cup`.

Commit message:

```text
feat: add Python client for body runtime API
```

## Stage 7: Real Character Import

Only after placeholder runtime is stable:

- Add GLB/VRM character asset.
- Keep placeholder mode as fallback.
- Map existing protocol actions to real animation or simple bone/transform controls.

Commit message:

```text
feat: add switchable real character body implementation
```

## Development Guardrails

- Do not add training code before the runtime loop is stable.
- Do not add arbitrary bone control to the LLM protocol.
- Do not add new action names without implementation and tests.
- Keep placeholder body runnable even after real character import.
- Log every request and response as JSONL for future training data.
