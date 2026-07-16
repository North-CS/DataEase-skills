# Validation status

Last validated against DataEase `2.10.25` on 2026-07-16. Re-run the checks after upgrading DataEase, changing edition, replacing the gateway, or modifying authentication.

## Automated checks passed

- 58 Python unit/regression tests, including administrator-role detection, role-edit L3 enforcement, dynamic user-edit risk and role-state plan invalidation.
- Skill package structure and frontmatter validation (`Skill is valid!`).
- CLI parser/help smoke tests for all nine domains.
- Fresh Python and npm installation from both the release staging directory and the unpacked ZIP.
- 23/23 online capability probes available through AK/SK.
- Full read-only platform inventory with no failed module.
- Credential scan found no configured DataEase credential in tracked or generated Skill files.
- Email setting account, password and recipient slots are masked.
- Request-local connection, callback and recipient secrets are removed from server error messages/details.
- Live no-write user-create dry-runs resolved the real role metadata correctly: the organization-administrator role produced L3 with a confirmation token, while the ordinary-user role produced L1 without a token.

## Runtime-host validation

- Windows x64 is the currently verified Skill execution host.
- The live DataEase target and isolated external dependencies were exercised on CentOS Linux, but that does not count as running the Skill package itself under Linux.
- Linux and macOS code paths are designed for portability but remain release-matrix gaps until the package, dependencies, CLI, L3 token flow and Playwright capture are run on those hosts.
- Agent discovery and execution differ by client. See `compatibility.md`; do not convert a documentation-level compatibility claim into a tested claim without recording the client and version.

## Online isolated lifecycle checks passed

- Organization, role and user: create, edit, disable/enable, reset password and delete.
- Data-source folder: create, rename, L3 delete and no-residue verification.
- Dataset folder: create, rename, L3 delete and no-residue verification.
- System basic settings: read and idempotent save of the exact current 22-item value set.
- Webhook: create, privacy-safe readback, enable SSL, L3 delete and no residue.
- Scheduled report: future-dated create, privacy-safe info, stop, start, stop-before-delete, L3 delete and no residue.
- Dashboard: three-chart intelligent plan, unpublished create, API readback, 1920×1080 Playwright capture through ASK headers, L3 delete and no residue.
- Failed data-source validation: expected API failure with request secret absent from the error result.
- LDAP, OIDC, CAS, OAuth2 and SAML2 discovery/info endpoints: available and currently unconfigured.

## External dependency checks passed

- Disposable MySQL: database/user/table creation, DataEase `2.10.25` datasource validation and create, connection status `Success`, and synthetic 12-row query path.
- Physical-table dataset: official-version DTO create, seven-field/12-row preview, intelligent visual planning and four-chart unpublished dashboard generation.
- DingTalk: existing tenant configuration and robot group were used without changing the integration; `report fire-now` completed with `execStatus=2` (`SUCCESS`), followed by stop/delete cleanup.
- SMTP: an isolated standards-compatible SMTP sink received one 19,249-byte EML with subject, HTML body and image MIME part; report execution returned `SUCCESS`. The original seven-row QQ SMTP configuration was restored and matched the pre-test SQL hash.
- OIDC: disposable Keycloak `26.7.0` discovery, validation, save, enable, browser sign-in, DataEase callback, user auto-provisioning and workbench access all succeeded over the isolated HTTP test path. OIDC was then disabled, its zero-row baseline restored, the generated user deleted, and the container/image removed.
- Regression from live testing: DataEase `2.10.25` email save can append a second seven-row setting set instead of replacing it. The database was restored exactly and the Skill now blocks `setting-save --scope email` on this version while retaining `setting-validate`.

## Intentionally not claimed as end-to-end validated

- API/ExcelRemote data-source synchronization against a disposable remote source.
- WeCom, Lark or Larksuite callback/login delivery using a real enterprise tenant. Their common API, redaction and L3 safety paths are covered, but DingTalk success does not prove provider-specific tenant behavior.
- LDAP, CAS, OAuth2 or SAML2 login with an external identity provider. OIDC was validated only with the disposable Keycloak realm.
- Production-recipient SMTP delivery. MIME and scheduler delivery were validated against an isolated sink; no real mailbox was contacted.
- Public-HTTPS enterprise callback behavior. The current DataEase instance is HTTP-only, so provider flows that require a publicly trusted HTTPS callback still need a suitable gateway/domain.

The OIDC load test ran on a 7.6-GB host while swap was inactive and the root disk was 90% full. The host later stopped responding at the application and SSH-banner layers, but neither the persisted kernel logs nor Docker container state recorded an OOM kill. After a console reboot, the existing 2-GB swap partition was active; the definite recovery issue was a missing `docker.service` unit. It was restored from the DataEase `2.10.25` offline installer and enabled for future boots. Treat the incident as unclassified host/runtime resource starvation rather than a proven OOM, and keep disposable identity providers off a constrained production DataEase node.

Do not promote an item from this final section to “tested” merely because its endpoint exists. Supply an isolated external dependency, run the dry-run/apply flow, verify the external observation, and clean the test resource first.
