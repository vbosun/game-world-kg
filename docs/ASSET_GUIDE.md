# Asset Guide

## Phase 1 Asset Rule

Do not block MVP progress on real character assets. The first implementation should use a placeholder body made from primitive nodes.

## Placeholder Body

Recommended nodes:

```text
PlaceholderBody
├── BodyMesh           capsule or box
├── HeadMesh           sphere
├── LeftArmMesh        box
├── RightArmMesh       box
├── RightHandSocket    Marker3D
├── HeadLookTarget     Marker3D
└── AnimationPlayer
```

## Test Room

Recommended nodes:

```text
TestRoom
├── Floor
├── Chair
├── Table
├── Cup
├── UserAnchor
└── Light
```

## Real Character Import Later

When importing a real character from Blender:

1. Export GLB/glTF from Blender.
2. Keep skeleton and mesh names stable.
3. Keep materials simple first.
4. Verify that the model opens in Godot before connecting it to runtime actions.
5. Keep `PlaceholderBody` as fallback.

## Real Character Requirements

Minimum requirements before replacing placeholder:

- Model displays correctly.
- Materials are acceptable.
- Skeleton does not explode.
- At least idle pose works.
- Head/hand nodes can be located for gaze and prop attachment.

## Animation Requirements

MVP can use simple node transforms. Real animation mapping can come later.

Action mapping target:

```text
idle        → idle animation or default pose
wave        → wave animation or right arm transform
sit_chair   → sit animation or pose transition
stand_up    → stand animation or pose transition
hold_cup    → prop attachment + holding pose
look_at_user→ head/eye look-at control
```

## Avoid in MVP

- Cloth physics.
- Auto-fitting clothes.
- Dynamic undressing/dressing animation.
- Arbitrary bone control from LLM.
- Large action libraries before the protocol loop works.
