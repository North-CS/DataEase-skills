# Safety and confirmation

## Risk levels

| Level | Examples | Required behavior |
|---|---|---|
| L0 | List, inspect, profile, capture, diagnose | Execute directly |
| L1 | Create dashboard, DataV, form, ordinary user, ordinary data resource or task | Dry-run, then apply by plan ID |
| L2 | Existing visual component/field/theme/filter edit, dataset-model or calculated-field save, native business-data export, publish ordinary resources, edit user profile without changing roles, create Webhook, stop report | Show diff/snapshot, then apply by plan ID |
| L3 | Resource or row/column permission change, restore/migrate, solution execution, plugin/driver lifecycle, delete, truncate, report fire/start/create, role edit, user role assignment, administrator creation, authentication/integration change, user disablement, data-source connection/schema change | Snapshot/compensation statement, plan ID and confirmation token |

Plans expire after 30 minutes. Re-run dry-run if the target, organization, version, resource state or requested payload changes.

## Permission-sensitive administration

- `admin role-edit` is always L3. Treat a role definition edit as permission-sensitive even when the submitted DTO currently changes only its name or description.
- `admin role-permission-set` is always L3. It snapshots the selected menu/resource matrix, binds the role, scope and desired matrix to the plan digest, applies only with the matching confirmation token, and verifies the result by readback.
- `admin role-edit` cannot change the permission matrix. Read it with `admin role-permissions` and change it with `admin role-permission-set`. If the current edition/version does not expose the required `/auth/*Permission` endpoint, return `capability_unavailable`; never silently fall back to browser automation for a permission mutation.
- `admin user-edit` is L3 whenever the normalized `roleIds` set differs from the current user. Reordering the same role IDs does not count as a permission change; other profile-only edits remain L2.
- `admin user-create` is L3 when any selected DataEase role is an administrator role. DataEase V2 identifies the built-in organization-administrator role structurally as `root=true` and `readonly=false`; do not depend on a localized role name.
- The selected role set and its administrator classification are digest-bound to the plan. A missing, hidden, removed or reclassified role invalidates the plan before the create request is sent.
- Older plans with a lower risk classification are rejected with `plan_risk_changed`; generate a new dry-run instead of attempting to reuse them.
- `permission apply` binds exact user/role identity and every resource scope, verifies each matrix and attempts to restore already-applied scopes if a later scope fails.
- `model permission-save/delete` is L3 because row/column rules change data exposure even when no role membership changes.
- `transfer restore/migrate` binds target instance, organization, version, bundle digest and ID mapping. Data-source credentials are never taken from a portable bundle.
- `plugin`/`driver` plans bind the exact package SHA-256. Rollback requires a separately retained known-good package because DataEase exposes no plugin-package download API.
- `solution execute` requires confirmed metric definitions and uses a compensating transaction. Any failed compensation is returned explicitly; never describe partial rollback as success.

## Version gates

- Run `system adapter` before using advanced mutations.
- The adapter is source-verified through DataEase `2.10.25`. A higher version is read-only by default.
- `DATAEASE_ALLOW_UNVERIFIED_VERSION=true` is only for an isolated compatibility run after inspecting endpoint/DTO differences. Do not set it globally in production.
- Unsupported features return `capability_unavailable`; do not silently switch to UI automation for permissions, plugins or destructive operations.

Setting saves also require an unchanged, complete and unique pkey set. Version-specific endpoints that failed destructive readback testing are blocked even when the caller supplies a valid plan; DataEase `2.10.25` email save is one such endpoint, while its non-mutating validation endpoint remains available.

## Secrets

- Read secrets only from environment variables, `.env`, secure host input or a managed secret store.
- When an official request requires a secret, pass the spec through standard input or a protected temporary file outside the repository. Delete the temporary file after use.
- Never place secrets in shell arguments, screenshots, plans, snapshots, audit logs, exception messages or public result objects.
- Secret-bearing specs are digest-bound: dry-run and apply must receive byte-equivalent JSON values, while the plan stores only a SHA-256 digest.
- Treat API Keys as full-account credentials unless the server proves narrower scope.
- Redact keys containing password, secret, token, signature, access key, private key or authorization markers.
- Treat report recipients, email accounts, Webhook URLs and callback query strings as sensitive even when their field names do not contain a secret marker.

## Destructive operations

Before an L3 action:

1. Resolve the exact resource ID and organization.
2. Read the current state and dependent resources.
3. Create a recoverable snapshot where the API supports it.
4. Explain what cannot be restored automatically.
5. Generate a confirmation token in the dry-run plan.
6. Apply only when the user confirms that exact plan and token.
7. Read back the target and write an audit entry.

Refuse broad instructions such as “clean everything” until the exact resource set is enumerated and confirmed.
