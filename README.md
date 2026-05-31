# AI Body Runtime

AI Body Runtime is a local virtual body runtime that lets an LLM or external program control a 3D character through a strict JSON body intent protocol.

The project starts with a deliberately small MVP: a placeholder body, a test room, a few whitelisted actions, expression/camera/prop controls, screenshots, and a local control API. The goal is to make the body a stable external device for an existing LLM, not to train a new brain.

## MVP Goals

- Receive a `BodyIntent` JSON command.
- Execute predefined body actions.
- Control expression, prop, gaze, and camera.
- Capture screenshots.
- Return structured body state.
- Record logs for future imitation/RL experiments.

## Non-goals for MVP

- No LLM training.
- No skeletal reinforcement learning.
- No open world.
- No complex cloth simulation.
- No arbitrary free-form bone control.
- No complex Skyrim-like equipment system.

## First Runtime Shape

```text
LLM / Python / Hermes
        ↓ BodyIntent JSON
AI Body Runtime
        ↓
Godot placeholder character
        ↓
BodyState JSON + screenshot path
```

## Repository Layout

```text
docs/              Design documents and development plan
protocol/          JSON schemas and example body commands
godot/             Godot 4.x runtime project skeleton
client/python/     Python client for runtime API
client/curl/       Curl request examples
codex_prompts/     Prompts for staged Codex implementation
tests/             Protocol and integration test placeholders
```

## Quick Start Roadmap

1. Read `docs/MVP.md`.
2. Implement or open `godot/project.godot` in Godot 4.x.
3. Run the placeholder scene.
4. Send example commands from `protocol/examples/`.
5. Verify a `BodyState` response and screenshot output.

## Body Intent Example

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

## Current Status

This repository currently contains the MVP plan, protocol, and project skeleton. The first implementation target is a placeholder Godot body runtime before importing real GLB assets.
