# Shared UI Rules

Follow the repository Node/Workflow contract rules. This package is shared source
for the public app and commercial hosts. Keep host authentication, secret values,
product navigation and Next server deployment out of shared presentation code.
Use StudioProvider's scoped client/store for customer data. Preserve standalone
compatibility and validate both the public app and a consuming host when changing
runtime boundaries. Read the owning Next app's installed docs for Next-specific
code; the package does not select another Next/React runtime.
