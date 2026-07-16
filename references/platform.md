# Platform and data operations

Run `system capabilities` before using platform modules. A false capability can mean unavailable edition, missing permission, incompatible API, or a connectivity error; inspect its reason and HTTP status.

## Supported read paths

- Version and identity: `/license/version`, `/user/info`
- Organizations: `/org/page/tree`, `/user/switch/{id}`
- Data sources: tree/types/detail/validate, folder/create/update/rename/delete, remote synchronization and sync logs
- Datasets: tree/detail/fields, folder/create/save/rename/delete and downstream-reference checks
- Visualization: `/dataVisualization/tree`
- Data filling: `/data-filling/tree`, `/data-filling/get/{id}`, form task paging, and safety-gated form/task creation through the official DTO endpoints
- Administration: organization, role and user list/create/edit/enable/reset/delete, with L3 confirmation for role edits, user role changes and administrator-user creation
- System settings: basic settings, defaults, request timeout, sharing and email configuration/validation; DataEase 2.10.25 email mutation is blocked because live readback exposed duplicate-row behavior
- Authentication: basic policy, MFA, HMAC, and LDAP/OIDC/CAS/OAuth2/SAML2 discovery, validation, save and enable state
- Integrations: WeCom, DingTalk, Lark and Larksuite information, validation, save and enable state
- Automation: scheduled-report list/detail/log/create/update/fire/start/stop/delete and Webhook list/detail/options/save/SSL/delete

All returned platform configuration passes through recursive secret redaction. Report content/recipients and full Webhook URLs are omitted from public results. Email accounts/recipients, integration secrets, data-source credentials and SSO secrets are masked. Do not display raw configuration payloads without an additional domain-specific allowlist.

## Capability fallback

Use this fixed order:

1. Official system API.
2. A versioned internal adapter that explicitly matches the detected server version.
3. Playwright automation with stable selectors and post-action readback.
4. Manual instructions.

Never silently downgrade to browser automation. Include the adapter name in mutation results.

## Data profiling

The initial profile uses field metadata to recommend date, dimension, measure, identifier and sensitive roles. It does not claim value-level cardinality, null rate or distribution unless a data preview/query was actually executed.

## X-Pack

Organizations, users, roles, data filling, scheduled reports, platform integrations and authentication settings may require professional or enterprise capabilities. Return `capability_unavailable` rather than attempting undocumented operations when the module is absent.
