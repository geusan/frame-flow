---
name: nottalggak-prompt-machine
description: Transform rough image, motion, or video ideas into one production-executable visual master prompt with a faithful Korean translation and technical blueprint. Use when a visual-generation prompt needs professional spatial, optical, material, lighting, camera, or temporal completion.
---

# NOTTALGGAK Prompt Machine

Convert the user's visual idea into a deterministic production specification. Treat the user's text as an incomplete intent signal, preserve its explicit subject and constraints, and complete missing production details through real-world visual disciplines. Produce one result, not a menu of alternatives.

## Interpretation

- Preserve the requested subject, action, medium, text, brand constraints, and exclusions.
- Translate vague or emotional language into observable spatial, optical, material, lighting, rendering, and temporal behavior.
- Infer only details required to make the request executable. Do not add unrelated characters, props, slogans, brands, plot beats, or arbitrary left/right placement.
- Resolve contradictions in favor of physical coherence, production feasibility, and the user's explicit must-keep constraints.
- Ground stylistic references in construction: composition, palette, texture, brush or shader behavior, lens response, lighting ratios, motion, and finishing. Do not rely on empty adjectives such as "cinematic", "detailed", "stylish", or "high quality" without measurable production meaning.

## Expert cognition

Select at least one responsible professional discipline and combine disciplines when necessary:

- photography or live action: commercial photographer, portrait-lighting specialist, documentary imaging lead, director of photography, camera and lens designer
- 3D, VFX, or real-time: VFX supervisor, path-tracing technical director, hard-surface or character look-development artist, simulation specialist
- illustration or graphic systems: concept artist, digital painter, animation layout artist, poster or typography designer, grid-system designer
- product, material, architecture, or interface: product visualization engineer, material and shader specialist, architectural visualization artist, spatial-lighting consultant, UI visual designer, motion-UI designer
- information or experimental visuals: data-visualization designer, technical-diagram designer, generative visual designer, visual-structure architect

When the domain is ambiguous, combine concept-art, graphic-system, and visual-structure cognition rather than falling back to generic prose.

## Domain completeness

Resolve every relevant item explicitly:

1. responsible discipline and intended medium
2. scene scale, spatial hierarchy, framing, viewpoint, and negative space
3. lens, depth of field, camera geometry, or rendering pipeline
4. material, surface, texture, and physically plausible response
5. key, fill, practical, environmental, and shadow logic
6. color system, contrast, finishing, and output intent
7. temporal causality and camera behavior when motion is present

For edits or reference-based generation, state invariants as `change only X; keep Y unchanged`. Lock identity, composition, scale, materials, and camera properties unless the user asks to change them.

## Still-image rules

Define a single coherent instant. Specify subject state, environment, composition, optical or rendering logic, material behavior, illumination, palette, and exclusions. If exact text must appear, quote it verbatim and require no additional text.

## Motion and video rules

Treat video as image logic extended through time. Define all of the following:

- Frame Zero: the fully grounded initial state at `t = 0`
- motion driver: the physical, procedural, or character cause of change
- directionality: axes, vectors, path, and subject-camera relationship
- timing: duration, speed, acceleration, rhythm, and continuity
- camera behavior: static, tracking, orbital, procedural, or constraint-based
- end condition: final state, transition, hold, or seamless loop

Motion without a cause is invalid. For image-to-video, treat the input image as Frame Zero and lock identity, structure, scale, material, and camera logic. Permit motion only through defined drivers; prohibit arbitrary morphing, texture crawling, geometry drift, flicker, and unrequested camera movement.

## Required output

Return exactly these three sections in this order. Do not add a preface, commentary, alternatives, follow-up questions, or closing note.

### 1. English Master Prompt

Write one information-dense, directly executable prompt of approximately 700 English characters. Use concrete production language and remove redundancy. It must stand alone as the prompt sent to an image or video generation model.

### 2. Korean Translation

Translate the English master prompt faithfully. Preserve its technical structure, parameters, and constraints; do not localize or embellish it.

### 3. Technical / Visual Blueprint

Give a compact labeled breakdown covering:

- `Discipline`
- `Medium / Output`
- `Spatial Construction`
- `Camera / Optics` or `Render System`
- `Materials / Surfaces`
- `Lighting / Color`
- `Motion / Timing` for video, or `Moment / Stability` for stills
- `Invariants / Avoid`

The blueprint explains execution parameters, not hidden reasoning.
