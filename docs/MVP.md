# AI Body Runtime MVP

## Core Decision

The MVP does not train a brain. It treats existing LLMs as the brain and builds a controllable body runtime as an external device.

```text
Existing LLM / Hermes / Python client
        ↓
BodyIntent JSON
        ↓
Godot Body Runtime
        ↓
Action, expression, prop, gaze, camera, screenshot
        ↓
BodyState JSON
```

## MVP Scope

### Scene

- One small test room.
- One placeholder character.
- One chair.
- One cup.
- One user anchor.
- Three camera positions.

### Actions

- `idle`
- `look_at_user`
- `wave`
- `sit_chair`
- `stand_up`
- `hold_cup`

### Expressions

- `neutral`
- `smile`
- `surprised`

### Props

- `none`
- `cup`

### Cameras

- `front_medium`
- `front_full`
- `close_face`

## Non-goals

- No training.
- No real GLB character dependency in phase 1.
- No arbitrary bone-level control.
- No free-form action names from LLMs.
- No complex cloth or equipment system.
- No open world.

## MVP Acceptance Criteria

1. A Godot project can be opened and run.
2. The runtime can execute a local demo action sequence.
3. External callers can send a `BodyIntent` command.
4. Invalid actions are rejected or safely fall back to `idle`.
5. The runtime can return a structured `BodyState`.
6. The runtime can save a screenshot and return its path.
7. A Python client can call the runtime.
8. Each request is logged for future data collection.

## Why Placeholder First

The first goal is to validate the runtime protocol and control loop. Real models, GLB import, animation retargeting, IK, and visual polish should not block the first working loop.

## Future Phases

1. Replace placeholder body with GLB/VRM character.
2. Map protocol actions to real animations.
3. Add outfit slots and prop sockets.
4. Add richer body state observation.
5. Collect interaction data.
6. Train a small intent/action policy if rule-based mapping becomes insufficient.
