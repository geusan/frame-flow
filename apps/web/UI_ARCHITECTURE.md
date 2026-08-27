# Web UI architecture

The web app keeps the existing Frameflow visual language while using Tailwind CSS, shadcn-style source-owned components, and Radix UI primitives.

## Layers

- `src/components/ui`: generic, source-owned UI primitives. This is the only layer that imports `radix-ui` directly.
- `src/components/shared`: product-wide compositions such as page headers, search fields, and confirmation actions.
- `src/features`: feature-owned components. Complex workflow behavior belongs here instead of in route views.
- `src/styles/foundation.css`: design tokens, Tailwind theme mapping, reset, and application shell.
- `src/styles/integrations`: global selectors required by Vidstack and React Flow.
- `src/styles/features`: visual rules that are genuinely specific to a feature.
- `src/app/globals.css`: import-only global stylesheet entrypoint.

## Rules

1. Use a component from `components/ui` before creating a new button, field, dialog, popover, switch, tab, or accordion implementation.
2. Keep Radix behavior inside `components/ui`; feature code imports the local wrapper.
3. Add reusable colors, radii, shadows, and typography values to the semantic tokens in `foundation.css`.
4. Runtime geometry, media URLs, progress values, and React Flow coordinates may remain inline styles.
5. Keep third-party internal selectors in `styles/integrations`; do not convert them to arbitrary Tailwind selectors.
6. Do not add manual modal backdrops, `window.confirm`, or legacy button classes.

## Verification

Run the following before merging UI work:

```bash
npm run ui:check
npm run lint
npm run typecheck
npm run build
```

`ui:check` enforces the import boundary and blocks the legacy interaction patterns that this migration removed.
