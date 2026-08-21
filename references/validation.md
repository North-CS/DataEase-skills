# Validation status

The broad advanced-operation matrix was last validated against DataEase `2.10.25` on 2026-07-17. A focused live compatibility validation against DataEase `2.10.26` completed the local CSV/XLSX → datasource → dataset → Dashboard/DataV chain. Re-run relevant checks after upgrading DataEase, changing edition, replacing the gateway, or modifying authentication.

## Automated checks passed

- 180 Python unit/regression tests, including local CSV/XLSX generation without any DataEase configuration, file digest-bound datasource dry-runs, multipart Excel upload request formation, returned worksheet metadata handling, exact `2.10.26` file-workflow mutation allowance, and unverified-version mutation blocking, plus every v2.10.25 common-chart adapter rendering with native type/render/category conversion and authoritative field binding, dynamic multi-measure bar/line/area/radar/scatter/candle channels, pivot dimension/measure separation, bubble-map `extBubble` binding and unsupported-field rejection, indicator-native DTO defaults, China administrative-map defaults, per-view chart-data failure rejection, bounded rich-profile chart selection, interaction selector alias normalization, order-independent inferred cascades, explicit native query cascades, safe existing-query cascade rebuild and raw-cascade rejection, constraint-v3 all-chart-family requirement modeling, preview-density expansion, Dashboard/DataV collision-free packing, fixed-DataV density convergence and overcrowding rejection versus adaptive Dashboard expansion, responsive title/legend/axis/indicator/table typography and user scene overrides, background-aware query contrast, eleven built-in themes, custom/brand theme validation, SVG asset palette extraction, WCAG contrast correction, SVG preview generation, DataV indicator/table palette propagation, bounded transient-empty-preview retry, text-only visual quality scoring and apply-time enforcement, deterministic KPI/detail/title hierarchy gates, compact/standard/rich deterministic complexity profiles with role diversity, principle-derived design grammar selection, adaptive dashboard height and capture resolution, dashboard/DataV custom-resolution layout, dark-theme canvas preservation and density-aware decoration, native query-component DTO construction and published-control visibility rejection, safe same-dataset linkage planning, DataV grid-only/pixel layout and aggregation preservation, component move/field/theme patching and identity allowlists, SQL/union/sync-policy model validation, secret-free L3 sync plans, portable ID mapping, plugin package hashing/multipart transport, solution metric/quality gates and permission readback/rollback, multi-dataset planning, organization-context isolation, strict filling form/task DTO normalization and task lifecycle verification, custom user-password rejection, role/resource permission normalization, administrator-role detection, dynamic user-edit risk and runtime diagnostics.
- Skill package structure and frontmatter validation (`Skill is valid!`).
- CLI parser/help smoke tests for all 15 domains.
- Fresh Python and npm installation from both the release staging directory and the unpacked ZIP.
- The 25/25 online capability baseline was available through AK/SK, including the role-permission matrix, plugin and driver probes.
- Full read-only platform inventory with no failed module.
- Credential scan found no configured DataEase credential in tracked or generated Skill files.
- DataV deploy serialization preserves explicit pixel layouts, derives pixel geometry from grid-only custom layouts, and keeps automatically generated layouts distinct instead of stacking components.
- Filling-task aliases are normalized to the official DTO, conflicting aliases and unknown keys are rejected, and the normalized payload is digest-bound to the plan.
- Role-permission matrices are covered by mocked endpoint lifecycle tests. An isolated test role was granted and then revoked real datasource, dataset and DataV permissions through the L3 plan/apply/readback path.
- A real non-root role's menu, datasource, dataset, dashboard, DataV and data-filling permission matrices were read successfully through the new command without mutation.
- A live three-dataset retail plan used every selected dataset and returned cross-dataset relationship candidates, KPI candidates and explicit confirmation requirements without creating a visualization.
- Email setting account, password and recipient slots are masked.
- Request-local connection, callback and recipient secrets are removed from server error messages/details.
- Live no-write user-create dry-runs resolved the real role metadata correctly: the organization-administrator role produced L3 with a confirmation token, while the ordinary-user role produced L1 without a token.
- DataEase source tags were compared for advanced adapter routing: 2.7 legacy visual detail, 2.8+ request-style detail, 2.10.10+ linkage resource-table path, plugin availability from 2.8 and native dataset export from 2.10. The mutation ceiling is `2.10.25`.
- DataEase `2.10.26` focused compatibility lifecycle: an AI-generated 6×5 XLSX was uploaded through `/datasource/uploadFile` and saved as an Excel datasource; its returned physical table and field DTOs created the first dataset through the current UI-shaped `union`/`allFields` payload; a compact six-chart DataV was published, read back and passed 6/6 real chart-data requests. All temporary datasource, dataset and DataV resources were deleted afterward. Only this `file_datasource` workflow is marked mutation-verified at `2.10.26`; advanced model, permission, plugin, migration and authentication writes remain protected.
- Advanced modules have both offline transformation/gate coverage and the isolated live lifecycle coverage listed below. Plugin mutation and true two-instance migration remain explicit gaps.

## Runtime-host validation

- Windows x64 is verified for the complete package, Python CLI, npm wrappers and Playwright capture paths.
- The Skill's Python CLI, L3 plan/token flow and full unit/regression suite are also verified inside a constrained Linux container on the CentOS DataEase host.
- Native Linux Playwright capture and all macOS paths remain release-matrix gaps.
- Agent discovery and execution differ by client. See `compatibility.md`; do not convert a documentation-level compatibility claim into a tested claim without recording the client and version.

## Online isolated lifecycle checks passed

- Organization, role and user: create, edit, disable/enable, reset password and delete.
- Data-source folder: create, rename, L3 delete and no-residue verification.
- Dataset folder: create, rename, L3 delete and no-residue verification.
- System basic settings: read and idempotent save of the exact current 22-item value set.
- Webhook: create, privacy-safe readback, enable SSL, L3 delete and no residue.
- Scheduled report: future-dated create, privacy-safe info, stop, start, stop-before-delete, L3 delete and no residue.
- Dashboard: three-chart intelligent plan, unpublished create, API readback, 1920×1080 Playwright capture through ASK headers, L3 delete and no residue.
- Dashboard repair regression: an existing published dashboard that failed before canvas mount was repaired in place by restoring native indicator fields, component renderers, event envelopes and query-component background metadata; all 11 non-query chart-data requests passed, the resource was republished, and a 1920×1080 Playwright capture mounted a complete canvas.
- Map/layout regression: the repaired dashboard's two previously blank maps rendered against the China administrative map and its analytical rows were replanned. A fresh 11-chart dashboard with four KPIs, two maps, trend, composition, ranking, comparison, detail table and query component then passed 11/11 real chart-data calls and a native 1920×1440 Playwright capture; the disposable resource was deleted afterward.
- Query-component regression: the repaired dashboard's previously blank 160-pixel filter area now renders one native VQuery component with three visible controls (统计月份、大区、省级行政区) and a query button. Playwright reports `visibleQueryComponents=1` and `visibleQueryConditions=3`.
- Query-cascade/theme regression: a live dashboard created and published a same-dataset 大区→省级行政区 cascade, read back the compound dataset/query/field IDs, rendered both controls and all chart data, and captured dark-theme query labels, inputs, borders and buttons with automatically corrected contrast.
- Intelligent-theme regression: a corporate-brand medical dashboard dry-run generated three SVG choices and WCAG metadata without creating a resource. The selected custom palette was then created and published against DataEase `2.10.25`; chart data passed, the Playwright canvas capture completed, and the bar renderer used the requested `#008C85` brand color rather than the DataEase default blue.
- DataV parity regression: an energy-green 1920×1080 screen was published with KPI indicator, China map, monthly line, donut composition, detail table and 大区→省级行政区 VQuery cascade. All five real chart-data calls passed; capture reported one visible query component, two visible conditions, no loading masks, and a complete canvas. The first transient empty-page attempts were cleaned up, bounded retry was added, and the final indicator, borders, line, map and table styles all used the energy palette.
- Text-only-model regression: `visual autopilot` received only dataset name, title, visual kind, theme and complexity. It produced a six-component compact DataV plan, three text-described SVG theme candidates, an A/100 machine-readable quality result and `multimodal_required=false`; no model-authored visual spec or image interpretation was used.
- Failed data-source validation: expected API failure with request secret absent from the error result.
- LDAP, OIDC, CAS, OAuth2 and SAML2 discovery/info endpoints: available and currently unconfigured.
- MySQL physical, multi-table join, SQL and parameterized SQL datasets: deterministic DTO preparation, create, field/readback and preview paths.
- Calculated field: create with void-response recovery and dataset-detail readback.
- Row and column permissions: real user row filter and column prohibition create/readback/delete using exact DataEase `2.10.25` DTOs.
- Existing DataV editing: component geometry/style, view title/filter, measure field/aggregation, theme and server-side linkage save/update/remove with snapshot-canvas readback.
- Portable transfer: same-instance visual backup/restore/migrate with fresh internal view IDs and linkage recreation; dataset restore with table/field/expression ID remapping and row/column permission restoration.
- Resource orchestration: isolated role grant/readback/revoke for datasource, three datasets and multiple DataV screens.
- One-stop solution: two-dataset sample quality gate, confirmed KPI, five-chart unpublished DataV creation and role screen permission grant. Exact permission readback and compensating rollback are additionally regression-tested.
- Plugin/driver inventory and plugin-package validation: live inventory plus valid/invalid archive inspection and L3 install dry-run; no package was installed.
- Synchronization: live cron validation returned five next-run timestamps. Exact `syncSetting` persistence and silent-ignore rejection are regression-tested; the disposable direct-MySQL source has no scheduled-sync DTO.
- Native dataset export returned a valid XLSX artifact.
- DataEase `previewSql` on this version fails inside the server's SQL-log mapper because its reserved `sql` column is not quoted; SQL dataset create and normal preview paths still succeeded.

## External dependency checks passed

- Disposable MySQL: database/user/table creation, DataEase `2.10.25` datasource validation and create, connection status `Success`, and synthetic 12-row query path.
- Physical-table dataset: official-version DTO create, seven-field/12-row preview, intelligent visual planning and four-chart unpublished dashboard generation.
- DingTalk: existing tenant configuration and robot group were used without changing the integration; `report fire-now` completed with `execStatus=2` (`SUCCESS`), followed by stop/delete cleanup.
- SMTP: an isolated standards-compatible SMTP sink received one 19,249-byte EML with subject, HTML body and image MIME part; report execution returned `SUCCESS`. The original seven-row QQ SMTP configuration was restored and matched the pre-test SQL hash.
- OIDC: disposable Keycloak `26.7.0` discovery, validation, save, enable, browser sign-in, DataEase callback, user auto-provisioning and workbench access all succeeded over the isolated HTTP test path. OIDC was then disabled, its zero-row baseline restored, the generated user deleted, and the container/image removed.
- Regression from live testing: DataEase `2.10.25` email save can append a second seven-row setting set instead of replacing it. The database was restored exactly and the Skill now blocks `setting-save --scope email` on this version while retaining `setting-validate`.

## Intentionally not claimed as end-to-end validated

- True cross-instance portable restore/migrate against a second DataEase installation. The same-instance branch, collision handling, ID remapping and permission/linkage restoration are covered.
- Plugin/database-driver install, upgrade, rollback or uninstall. Only package inspection and API/source compatibility are currently covered.
- API/ExcelRemote data-source synchronization against a disposable remote source.
- WeCom, Lark or Larksuite callback/login delivery using a real enterprise tenant. Their common API, redaction and L3 safety paths are covered, but DingTalk success does not prove provider-specific tenant behavior.
- LDAP, CAS, OAuth2 or SAML2 login with an external identity provider. OIDC was validated only with the disposable Keycloak realm.
- Production-recipient SMTP delivery. MIME and scheduler delivery were validated against an isolated sink; no real mailbox was contacted.
- Public-HTTPS enterprise callback behavior. The current DataEase instance is HTTP-only, so provider flows that require a publicly trusted HTTPS callback still need a suitable gateway/domain.

The OIDC load test ran on a 7.6-GB host while swap was inactive and the root disk was 90% full. The host later stopped responding at the application and SSH-banner layers, but neither the persisted kernel logs nor Docker container state recorded an OOM kill. After a console reboot, the existing 2-GB swap partition was active; the definite recovery issue was a missing `docker.service` unit. It was restored from the DataEase `2.10.25` offline installer and enabled for future boots. Treat the incident as unclassified host/runtime resource starvation rather than a proven OOM, and keep disposable identity providers off a constrained production DataEase node.

Do not promote an item from this final section to “tested” merely because its endpoint exists. Supply an isolated external dependency, run the dry-run/apply flow, verify the external observation, and clean the test resource first.
