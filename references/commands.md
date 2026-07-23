# Command reference

Global options must appear before the domain:

```bash
python scripts/dataease.py [--env-file PATH] [--base-url URL] [--org-id ID] [--insecure] <domain> <action>
```

Use `--insecure` only for a known test instance. Prefer `DATAEASE_CA_BUNDLE` for private certificate authorities.

## System and inventory

```bash
python scripts/dataease.py system doctor
python scripts/dataease.py system capabilities
python scripts/dataease.py system adapter
python scripts/dataease.py --org-id 1 inventory scan
```

## Data

```bash
python scripts/dataease.py dataset list
python scripts/dataease.py dataset fields --dataset "销售数据"
python scripts/dataease.py dataset profile --dataset "销售数据"
python scripts/dataease.py dataset plan --dataset "销售数据" --title "经营分析" --busi-type dashboard
python scripts/dataease.py dataset plan --dataset "销售" --dataset "目标" --dataset "库存" --title "经营驾驶舱" --busi-type dataV
python scripts/dataease.py datasource list
python scripts/dataease.py datasource types
python scripts/dataease.py datasource tables --datasource-id 123
python scripts/dataease.py datasource table-fields --datasource-id 123 --table-name sales
python scripts/dataease.py datasource validate --id 123
python scripts/dataease.py datasource validate-spec --spec datasource.json
python scripts/dataease.py datasource sync-logs --id 123 --page 1 --size 20

# Folder lifecycle
python scripts/dataease.py datasource folder-create --name "业务数据源"
python scripts/dataease.py datasource folder-create --name "业务数据源" --apply --plan-id plan-xxxxxxxx
python scripts/dataease.py datasource rename --id 123 --current-name "业务数据源" --name "核心数据源"
python scripts/dataease.py datasource rename --id 123 --current-name "业务数据源" --name "核心数据源" --apply --plan-id plan-xxxxxxxx

# Official BusiDsRequest-shaped spec. Repeat the exact spec at apply time.
python scripts/dataease.py datasource create --spec datasource.json
python scripts/dataease.py datasource create --spec datasource.json --apply --plan-id plan-xxxxxxxx
python scripts/dataease.py datasource update --spec datasource.json --ack-no-rollback
python scripts/dataease.py datasource update --spec datasource.json --ack-no-rollback --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py datasource sync --id 123 --name "核心数据源"
python scripts/dataease.py datasource sync --id 123 --name "核心数据源" --apply --plan-id plan-xxxxxxxx
python scripts/dataease.py datasource delete --id 123 --name "核心数据源" --ack-no-rollback
python scripts/dataease.py datasource delete --id 123 --name "核心数据源" --ack-no-rollback --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN

python scripts/dataease.py dataset folder-create --name "主题数据集"
python scripts/dataease.py dataset rename --id 456 --current-name "旧名称" --name "新名称"
python scripts/dataease.py dataset create --spec dataset.json
python scripts/dataease.py dataset update --spec dataset.json
python scripts/dataease.py dataset delete --id 456 --name "新名称" --ack-no-rollback
```

`datasource sync` maps to DataEase `syncApiDs` and is intentionally limited to API and ExcelRemote source types.

`datasource tables` returns DataEase's version-native `DatasetTableDTO` records. `datasource table-fields` reuses that DTO, fills the physical-table `info` descriptor when the server omits it, and returns the exact field DTOs required by dataset/model specs. This avoids inventing field IDs or types.

`dataset plan` accepts repeated `--dataset` arguments. Multi-dataset plans place charts from every usable dataset on one canvas and return same-name relationship candidates, KPI candidates and explicit confirmation requirements. They do not silently create joins or claim that matching field names prove the same business grain. Save only `result`, not the surrounding envelope, as the input to `visual create`.

## Advanced modeling, editing, permissions and migration

```bash
python scripts/dataease.py visual inspect --resource-id 123 --busi-type dataV
python scripts/dataease.py visual patch --spec visual-patch.json
python scripts/dataease.py visual linkage --spec linkage.json

python scripts/dataease.py model inspect --dataset-id 456
python scripts/dataease.py model validate --spec dataset-model.json
python scripts/dataease.py model preview --preview-type sql --spec sql-preview.json
python scripts/dataease.py model save --spec dataset-model.json
python scripts/dataease.py model calculated-save --spec calculated-field.json
python scripts/dataease.py model permission-save --kind row --spec row-permission.json
python scripts/dataease.py model sync-policy --spec datasource-with-sync-setting.json --ack-no-rollback

python scripts/dataease.py permission inspect --subject-type role --subject-id 100 --scope all
python scripts/dataease.py permission apply --spec permissions.json

python scripts/dataease.py transfer backup --resource-type visual --resource-id 123 --busi-type dataV --output backup.json
python scripts/dataease.py transfer export --resource-type visual --resource-id 123 --busi-type dataV --output backup.json
python scripts/dataease.py transfer restore --spec restore.json --target-env-file target.env
python scripts/dataease.py transfer import --spec restore.json --target-env-file target.env
python scripts/dataease.py transfer migrate --spec restore.json --target-env-file target.env

python scripts/dataease.py plugin list
python scripts/dataease.py driver package-check --package driver.jar
python scripts/dataease.py plugin install --package extension.jar
python scripts/dataease.py plugin rollback --plugin-id 100 --package extension-old.jar

python scripts/dataease.py solution plan --spec sales-solution.json
python scripts/dataease.py solution execute --spec sales-solution.json
```

Mutation commands above follow the usual repeat-the-same-spec apply flow. Resource and row/column permissions, restore/migrate, extension lifecycle and `solution execute` are L3 and require `--confirm-token`. Full specs, endpoint/version behavior and rollback limits are in [advanced.md](advanced.md).

## Visualization

```bash
python scripts/dataease.py visual list --busi-type dashboard
python scripts/dataease.py visual capture --id 123 --busi-type dataV --pixel "1920*1080"

# Dry-run
python scripts/dataease.py visual create --spec visual.json

# Apply the exact plan returned above
python scripts/dataease.py visual create --apply --plan-id plan-xxxxxxxx

# Text-only / weaker-model autopilot: profile the dataset, select charts, interactions,
# theme and responsive layout deterministically, then return a normal create plan.
python scripts/dataease.py visual autopilot --dataset "销售明细" --title "销售驾驶舱" --busi-type dashboard --complexity standard
python scripts/dataease.py visual autopilot --dataset "销售明细" --title "销售大屏" --busi-type dataV --theme tech-blue --complexity compact

# Apply the exact autopilot plan returned above; no image understanding is required.
python scripts/dataease.py visual autopilot --apply --plan-id plan-xxxxxxxx

# Publish/unpublish uses the same two-step flow
python scripts/dataease.py visual publish --resource-id 123 --name "经营分析" --status 1
python scripts/dataease.py visual publish --apply --plan-id plan-xxxxxxxx

# L3 deletion requires an acknowledged no-rollback plan and its confirmation token.
python scripts/dataease.py visual delete --resource-id 123 --name "经营分析" --busi-type dashboard --ack-no-rollback
python scripts/dataease.py visual delete --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
```

Unified `visual create` and `visual autopilot` publish the resource and then perform deterministic read-back, chart-data and optional capture checks. If a required post-create check fails, the workflow reports the failed stage and attempts compensating cleanup. Screenshot interpretation is an optional visual enhancement, not a success prerequisite; text-only models can rely on the machine-readable quality report and verification results.

## Data filling and administration

```bash
python scripts/dataease.py filling list
python scripts/dataease.py filling get --id 123
python scripts/dataease.py filling tasks --form-id 123 --page 1 --size 20
python scripts/dataease.py filling rows --form-id 123 --page 1 --size 20

# Create a folder/form or task from an official DataEase DTO-shaped JSON spec.
python scripts/dataease.py filling create --spec filling.json
python scripts/dataease.py filling create --apply --plan-id plan-xxxxxxxx
python scripts/dataease.py filling task-create --spec task.json
python scripts/dataease.py filling task-create --apply --plan-id plan-xxxxxxxx

# Repeat the same row spec at apply time; the plan stores only its SHA-256 digest.
python scripts/dataease.py filling row-save --spec row.json
python scripts/dataease.py filling row-save --spec row.json --apply --plan-id plan-xxxxxxxx
python scripts/dataease.py filling row-delete --form-id 123 --row-id 456 --ack-no-rollback
python scripts/dataease.py filling row-delete --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py filling truncate --form-id 123 --name "客户回访" --ack-no-rollback
python scripts/dataease.py filling truncate --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN

python scripts/dataease.py filling delete --id 123 --name "测试文件夹" --ack-no-rollback
python scripts/dataease.py filling delete --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN

python scripts/dataease.py admin organizations
python scripts/dataease.py admin users --page 1 --size 100
python scripts/dataease.py admin roles --keyword "销售"
python scripts/dataease.py admin role-permissions --id 123 --scope all
python scripts/dataease.py admin settings
python scripts/dataease.py admin authentication
python scripts/dataease.py admin integrations

# Organization, role and user writes use official DTO-shaped specs.
python scripts/dataease.py admin organization-create --spec organization.json
python scripts/dataease.py admin role-create --spec role.json
python scripts/dataease.py admin user-create --spec user.json
python scripts/dataease.py admin role-edit --spec role.json
python scripts/dataease.py admin role-edit --spec role.json --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py admin role-permission-set --spec role-permissions.json
python scripts/dataease.py admin role-permission-set --spec role-permissions.json --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py admin user-edit --spec user.json
python scripts/dataease.py admin user-edit --spec user.json --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py admin user-enable --id 123 --account codex_user --enable false
python scripts/dataease.py admin user-reset-password --id 123 --account codex_user --ack-no-rollback
python scripts/dataease.py admin user-delete --id 123 --account codex_user --ack-no-rollback
```

`role-edit` only changes role metadata (`name` and `desc`) and is always L3. Use `role-permissions` and `role-permission-set` for one role's menu/resource matrices; use `permission apply` to orchestrate several resource scopes for either a user or role. These commands treat the spec as the complete desired direct-permission matrix, convert omissions to DataEase `weight: 0` revocations, snapshot and verify readback. `role-permission-set` deliberately rejects embedded row/column changes; manage those independent rules with L3 `model permission-save/delete`. If the target edition/version lacks the required endpoint, the command returns `capability_unavailable`. `user-edit` is L3 only when normalized `roleIds` change; otherwise it is L2. `user-create` is L3 when a selected role is the DataEase administrator role (`root=true`, `readonly=false`), and L1 for ordinary roles.

### Data-filling task spec

`task-create` normalizes the common aliases `assignUsers`/`reciUsers` to `uidList` and `rateValue` to `rateVal`. It rejects unknown fields before DataEase can silently ignore them. Prefer the official DTO names:

```json
{
  "formId": 123,
  "name": "月度数据收集",
  "reciFlagList": [1],
  "msgType": 0,
  "msgTitle": "请填写月度数据",
  "msgContent": "请在截止时间前完成填报。",
  "uidList": [1001, 1002],
  "ridList": [],
  "fillType": 0,
  "fitType": 0,
  "fitColumn": "",
  "rateType": 1,
  "oneTimeType": 0,
  "rateVal": "2026-08-01 09:00:00",
  "startTime": 1785546000000,
  "endTime": 1786150800000,
  "publishRangeTime": 7,
  "publishRangeTimeType": 1,
  "status": 0,
  "formExtSetting": "{}",
  "formFilterSetting": "{}"
}
```

Read the form/task detail from the target DataEase version before changing scheduling enums. `uidList` and `ridList` accept numeric IDs; comma-separated strings are normalized for compatibility.

### Role permission spec

```json
{
  "roleId": 123,
  "scope": "dataset",
  "permissions": [
    {"id": 456, "weight": 7, "ext": 0}
  ]
}
```

Scopes are `menu`, `datasource`, `dataset`, `panel`, `screen` and `data_filling`; `dashboard` maps to `panel`, and `datav` maps to `screen`. Dataset permission items may additionally include official `columnPermissions` and `rowPermissions` objects. Preserve their server-returned shape instead of inventing filters.

## Settings, integrations and SSO

```bash
python scripts/dataease.py admin setting-read --scope system-basic
python scripts/dataease.py admin setting-read --scope email
python scripts/dataease.py admin setting-save --scope system-basic --spec settings.json
python scripts/dataease.py admin setting-save --scope auth-mfa --spec mfa.json --ack-no-rollback
python scripts/dataease.py admin setting-validate --scope email --spec email.json

python scripts/dataease.py admin integration-validate --provider dingtalk --spec dingtalk.json
python scripts/dataease.py admin integration-save --provider lark --spec lark.json --ack-no-rollback
python scripts/dataease.py admin integration-enable --provider lark --enable true

python scripts/dataease.py admin sso-list
python scripts/dataease.py admin sso-status
python scripts/dataease.py admin sso-info --provider oidc
python scripts/dataease.py admin sso-validate --provider oidc --spec oidc.json
python scripts/dataease.py admin sso-save --provider oidc --spec oidc.json --ack-no-rollback
python scripts/dataease.py admin sso-enable --id 123 --name oidc --enable true
```

Authentication, integration and SSO saves are L3. Repeat the exact spec at apply time and supply the plan's confirmation token.

Setting replacement specs must contain the complete current pkey set with no duplicates. On DataEase `2.10.25`, `admin setting-save --scope email` is intentionally blocked because the official save endpoint can append duplicate rows; use `setting-validate` and change email settings in a separately controlled maintenance workflow.

## Scheduled reports and Webhooks

```bash
python scripts/dataease.py report list --keyword "经营周报"
python scripts/dataease.py report info --id 123
python scripts/dataease.py report logs --id 123 --page 1 --size 20
python scripts/dataease.py report create --spec report.json
python scripts/dataease.py report update --spec report.json --ack-no-rollback
python scripts/dataease.py report fire-now --id 123 --name "经营周报"
python scripts/dataease.py report stop --id 123 --name "经营周报"
python scripts/dataease.py report start --id 123 --name "经营周报"
python scripts/dataease.py report delete --id 123 --name "经营周报" --ack-no-rollback

python scripts/dataease.py webhook list
python scripts/dataease.py webhook get --id 123
python scripts/dataease.py webhook options
python scripts/dataease.py webhook save --spec webhook.json
python scripts/dataease.py webhook ssl --id 123 --name "告警入口" --ssl true
python scripts/dataease.py webhook delete --id 123 --name "告警入口" --ack-no-rollback
```

Report public results exclude content and recipient lists. Webhook public results expose only endpoint scheme/host/port, never the full URL or secret.

## Result envelope

Success:

```json
{
  "schema_version": 1,
  "ok": true,
  "operation": "dataset.profile",
  "result": {},
  "warnings": []
}
```

Failure:

```json
{
  "schema_version": 1,
  "ok": false,
  "error": {
    "code": "dataset_not_found",
    "message": "...",
    "stage": "dataset",
    "retryable": false,
    "details": {}
  }
}
```
