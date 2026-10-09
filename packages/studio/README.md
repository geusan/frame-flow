# Shared Studio UI

`@video-canvas/studio` owns reusable Canvas, Workflow, Node Inspector, media and
execution views. The public Next application and commercial hosts consume the
same source. It is a React library, not a running Next app or an iframe product.

Hosts own authentication, product navigation, routes, branding and deployment.
Mount `StudioProvider` with an immutable `ApiTransport` scoped to the authenticated
workspace. Use a new keyed provider for a different user/workspace/role. The
provider owns its API client, UI store and cancellation lifetime; authenticated
customer drafts are not written to browser localStorage. API authorization stays
server-authoritative. No secrets belong in the package or browser bundle.

Import reusable client views from `@video-canvas/studio` and global UI styles from
`@video-canvas/studio/styles.css`. Next hosts transpile the package; React,
React DOM and Next are peer dependencies provided by the host. Internal Node
Definition/default/port/editor contracts retain their existing Source of Truth.
The package does not copy or reinterpret those contracts for a commercial app.

The public standalone application retains its routes and legacy local recovery.
The commercial host supplies product-specific composition instead of mounting
the standalone application's shell, routes or server.
