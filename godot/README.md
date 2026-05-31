# Godot Runtime Skeleton

This directory will contain the Godot 4.x implementation of AI Body Runtime.

## Planned Structure

```text
godot/
├── project.godot
├── scenes/
│   ├── Main.tscn
│   ├── TestRoom.tscn
│   ├── BodyRuntime.tscn
│   ├── PlaceholderBody.tscn
│   └── CameraRig.tscn
├── scripts/
│   ├── body_api_server.gd
│   ├── body_runtime.gd
│   ├── body_intent.gd
│   ├── body_state.gd
│   ├── action_controller.gd
│   ├── expression_controller.gd
│   ├── prop_controller.gd
│   ├── gaze_controller.gd
│   ├── camera_controller.gd
│   ├── screenshot_controller.gd
│   └── logger.gd
├── assets/
└── outputs/
```

## First Implementation Rule

Use a placeholder body first. Do not import real GLB assets until the runtime loop works.
