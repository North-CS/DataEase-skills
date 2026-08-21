# Advanced platform orchestration

This reference covers component editing, dataset modeling, resource permissions, migration, extensions, solution orchestration and version adapters. These commands use the same JSON envelope, dry-run plan binding and L0-L3 rules as the rest of the Skill.

## Existing visual component editing

Inspect before editing:

```bash
python scripts/dataease.py visual inspect --resource-id 123 --busi-type dataV
```

`visual inspect` returns component IDs and geometry, chart view IDs, axes, dataset references and the linkage summary. A patch spec can combine layout, style, visibility, filters, field replacement and canvas theme changes:

```json
{
  "resource_id": "123",
  "name": "销售经营驾驶舱",
  "busi_type": "dataV",
  "component_updates": [
    {
      "id": "9001",
      "patch": {
        "x": 1,
        "y": 15,
        "sizeX": 18,
        "sizeY": 12,
        "style": {"left": 60, "top": 420, "width": 820, "height": 360},
        "linkageFilters": []
      }
    }
  ],
  "view_updates": [
    {
      "id": "9001",
      "patch": {
        "title": "区域利润",
        "customFilter": {"filter": []},
        "customStyle": {"legend": {"show": true}}
      }
    }
  ],
  "field_replacements": [
    {
      "view_id": "9001",
      "axis": "yAxis",
      "index": 0,
      "dataset_id": "456",
      "field_name": "利润",
      "aggregation": "sum"
    }
  ],
  "cascade_updates": [
    {
      "id": "query-component-id",
      "chains": [["大区", "省级行政区", "城市"]]
    }
  ],
  "theme": {
    "backgroundColor": "#050816",
    "dashboard": {"showGrid": false, "gapSize": 8}
  }
}
```

```bash
python scripts/dataease.py visual patch --spec visual-patch.json
python scripts/dataease.py visual patch --spec visual-patch.json --apply --plan-id plan-xxxxxxxx
```

The patch allowlist prevents changing component/view identities. Field replacement resolves the real target field metadata instead of inventing IDs and is intentionally limited to the view's current dataset. `cascade_updates` accepts explicit condition-name/ID chains or `"auto"` and rebuilds DataEase's native compound dataset/query/field IDs from the current VQuery conditions. Raw `cascade` JSON in `component_updates` is rejected because stale condition IDs can be stored successfully while remaining ineffective in the frontend. To rebind a whole chart to another dataset, use one `view_updates` patch containing the new `tableId` and complete axis arrays from the target version. `visual patch` is L2, snapshots the original canvas, binds the full spec digest and rejects stale targets.

Editing a published resource updates its working canvas; publish/unpublish remains a separate `visual publish` plan so a component edit never becomes externally visible implicitly.

Server-side linkage records use version-specific DTOs. Read the target version's current request first, then use:

```json
{
  "resource_id": "123",
  "name": "销售经营驾驶舱",
  "busi_type": "dataV",
  "action": "save",
  "payload": {
    "dvId": "123",
    "sourceViewId": "9001",
    "resourceTable": "snapshot",
    "linkageInfo": [
      {
        "targetViewId": "9002",
        "targetViewName": "区域明细",
        "targetViewType": "table-normal",
        "tableId": "456",
        "linkageActive": true,
        "linkageFields": [{"sourceField": "7001", "targetField": "7001"}],
        "targetViewFields": []
      }
    ]
  }
}
```

```bash
python scripts/dataease.py visual linkage --spec linkage.json
python scripts/dataease.py visual linkage --spec linkage.json --apply --plan-id plan-xxxxxxxx
```

Valid actions are `save`, `remove` and `update-active`. `save` replaces every linkage whose source is `sourceViewId`, so include the complete desired `linkageInfo` list returned by DataEase's linkage editor/gather API. `remove` requires `dvId` and `sourceViewId`; `update-active` additionally requires `activeStatus`. Editing reads and writes the working `snapshot` canvas. The all-linkage endpoint returns only a summary, not the complete original DTO, so rollback is manual from the snapshot and this limitation is reported in the plan.

## Dataset modeling

The `model` domain uses DataEase `DatasetGroupInfoDTO`, field DTO and row/column permission APIs:

```bash
python scripts/dataease.py model inspect --dataset-id 456
python scripts/dataease.py datasource tables --datasource-id 123
python scripts/dataease.py datasource table-fields --datasource-id 123 --table-name sales
python scripts/dataease.py model params --dataset-id 456 --dataset-id 789
python scripts/dataease.py model validate --spec dataset-model.json
python scripts/dataease.py model preview --preview-type sql --spec sql-preview.json
python scripts/dataease.py model preview --preview-type dataset --spec dataset-model.json
python scripts/dataease.py model save --spec dataset-model.json
python scripts/dataease.py model calculated-save --spec calculated-field.json
python scripts/dataease.py model permission-list --kind row --dataset-id 456
python scripts/dataease.py model permission-save --kind row --spec row-permission.json
python scripts/dataease.py model permission-delete --kind column --spec column-permission.json
python scripts/dataease.py model cron-preview --spec cron.json
python scripts/dataease.py model sync-policy --spec datasource-with-sync-setting.json --ack-no-rollback
```

DataEase `2.10.25` commonly returns a null top-level dataset `type`; the actual physical/SQL source kind lives in each `union[].currentDs.type`. The validator therefore infers physical-table, SQL and multi-table models from the official union tree while still accepting legacy explicit `type: db|sql|union` specs. Models require a non-empty official `union` tree with `currentDs`, `currentDsFields`, `childrenDs` and `unionToParent` unless a legacy direct SQL spec supplies `sql`.

For a new union model, `model preview` and `model save` deterministically fill missing Long-compatible table/field IDs, unique `dataeaseName`/`fieldShortName` aliases, source references and join-field DTOs before calling DataEase. This mirrors the essential client-side preparation performed by the web UI, keeps dry-run/apply payloads identical and prevents multiple fields from being persisted with the same alias. Existing model IDs and fields are never regenerated. `allFields`, SQL parameters, calculated fields and sync settings must still come from the target DataEase version; use `inspect`, `datasource table-fields`, preview and `getSqlParams` before saving. Model saves are L2. Row and column permission changes are L3 because they change data exposure.

DataEase `2.10.25` row-permission creation requires both the singular `authTargetId` used by its save DTO and the `authTargetIds` compatibility list. Keep `tree` and its serialized `expressionTree` equivalent:

```json
{
  "datasetId": 456,
  "enable": true,
  "authTargetType": "user",
  "authTargetId": 1001,
  "authTargetIds": [1001],
  "tree": {
    "logic": "and",
    "items": [
      {
        "type": "item",
        "fieldId": 7001,
        "filterType": "logic",
        "term": "eq",
        "value": "电子",
        "timeValue": "",
        "enumValue": [],
        "timeType": "year",
        "subTree": null
      }
    ]
  },
  "expressionTree": "{\"logic\":\"and\",\"items\":[{\"type\":\"item\",\"fieldId\":7001,\"filterType\":\"logic\",\"term\":\"eq\",\"value\":\"电子\",\"timeValue\":\"\",\"enumValue\":[],\"timeType\":\"year\",\"subTree\":null}]}",
  "whiteListUser": "[]",
  "whiteListRole": "[]",
  "whiteListDept": "[]",
  "whiteListUsers": [],
  "whiteListRoles": [],
  "exportData": false
}
```

Column permission `permissions` is a JSON string in this version, not a nested object:

```json
{
  "datasetId": 456,
  "enable": true,
  "authTargetType": "role",
  "authTargetId": 100,
  "authTargetIds": [100],
  "permissions": "{\"enable\":true,\"columns\":[{\"id\":7002,\"name\":\"profit\",\"selected\":true,\"opt\":\"Prohibit\"}]}"
}
```

Use `opt: "Prohibit"` to hide a column. For `opt: "Desensitization"`, first copy the complete `desensitizationRule` object returned by the target version's UI/API; rule enums vary by version. Update/delete specs must include the record `id` returned by `permission-list`. The Skill performs a post-save/delete list readback and rejects silent server ignores.

`cron-preview` validates and previews datasource synchronization expressions through `/datasource/cronNextTimes`. `sync-policy` persists `syncSetting` through a complete DataEase data-source DTO, is L3, Base64-encodes object-form configuration in memory, binds only the spec digest to its plan and requires `--ack-no-rollback` because `hidePw` cannot recover the previous connection secret.

## Resource permission orchestration

The `permission` domain binds users or roles to dashboard, DataV, dataset, datasource or data-filling resources:

```json
{
  "subject_type": "role",
  "subject_id": 100,
  "identity": "销售经理",
  "scopes": {
    "datav": [{"id": 123, "weight": 7, "ext": 0}],
    "dataset": [{"id": 456, "weight": 3, "ext": 0}],
    "datasource": [{"id": 789, "weight": 1, "ext": 0}]
  }
}
```

```bash
python scripts/dataease.py permission inspect --subject-type role --subject-id 100 --scope all
python scripts/dataease.py permission apply --spec permissions.json
python scripts/dataease.py permission apply --spec permissions.json --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
```

Each scope is a complete desired direct-permission matrix. Omitted resource IDs are revoked using DataEase's required `weight: 0` incremental patch. The command is L3, requires exact subject identity, snapshots every scope, verifies readback and attempts to restore already-applied scopes if a later scope fails. Row/column filters use `model permission-*`, not this weight-matrix command.

## Backup, restore and cross-instance migration

Portable JSON bundles contain resource metadata/configuration, version information, relationships and explicit restore notes:

```bash
python scripts/dataease.py transfer backup --resource-type visual --resource-id 123 --busi-type dataV --output backups/sales-datav.json
python scripts/dataease.py transfer export --resource-type visual --resource-id 123 --busi-type dataV --output backups/sales-datav.json
python scripts/dataease.py transfer backup --resource-type dataset --resource-id 456 --output backups/sales-dataset.json
python scripts/dataease.py transfer inspect --bundle backups/sales-datav.json
```

Restore spec:

```json
{
  "bundle": "backups/sales-datav.json",
  "name": "销售经营驾驶舱（目标环境）",
  "pid": "0",
  "id_map": {
    "456": "8456",
    "789": "8789"
  },
  "overrides": {}
}
```

```bash
python scripts/dataease.py transfer restore --spec restore.json --target-env-file target.env
python scripts/dataease.py transfer import --spec restore.json --target-env-file target.env
python scripts/dataease.py transfer restore --spec restore.json --target-env-file target.env --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
python scripts/dataease.py transfer migrate --spec restore.json --target-env-file target.env
```

`export` is an explicit alias of portable `backup`; `import` is an alias of `restore`. Import/restore and `migrate` are L3. Plans bind the bundle SHA-256, target URL/organization/version and restore spec digest. `id_map` replaces exact scalar IDs recursively. Data source bundles never contain usable credentials; provide the complete target `configuration` in `overrides`. Dataset row/column permission DTOs are remapped and restored. Visual restore always generates new internal View IDs to prevent same-environment and cross-environment primary-key collisions, rewrites component references, recreates active server-side linkage fields and verifies the target linkage summary.

Portable bundles can contain filter literals, row-permission values and internal resource metadata. Treat them as sensitive artifacts: store them outside the repository, restrict filesystem access and encrypt them when moving between hosts.

Native dataset data export is separate because it may contain business records:

```bash
python scripts/dataease.py transfer native-export --resource-id 456 --output exports/sales.xlsx --ack-sensitive-export
python scripts/dataease.py transfer native-export --resource-id 456 --output exports/sales.xlsx --ack-sensitive-export --apply --plan-id plan-xxxxxxxx
```

Native export is L2 and dry-run first because the file contains business data. `--ack-sensitive-export` acknowledges that data will be written to the local path; it does not upload the file anywhere.

## Plugins and database drivers

DataEase exposes database drivers through the plugin subsystem. The `driver` domain is a driver-focused alias over the verified plugin APIs:

```bash
python scripts/dataease.py plugin list
python scripts/dataease.py driver list
python scripts/dataease.py plugin package-check --package extension.jar
python scripts/dataease.py plugin install --package extension.jar
python scripts/dataease.py plugin update --plugin-id 100 --package extension-new.jar
python scripts/dataease.py plugin rollback --plugin-id 100 --package extension-old.jar
python scripts/dataease.py plugin uninstall --plugin-id 100 --ack-no-rollback
```

Install, update, rollback and uninstall are L3. Plans bind the package SHA-256 and installed-plugin inventory. JAR packages are checked as ZIP containers and inspected for a manifest before upload. Rollback is an explicit update with a known-good previous package; DataEase does not expose a package download API. `driver list` returns all plugin records and adds a best-effort `driver_candidate` annotation because `PluginVO` has no standardized driver category field—verify `name`, `flag`, version and datasource types after changes. Inventory output omits oversized embedded icon/binary strings and returns their byte size plus SHA-256 instead, keeping Agent context bounded without hiding that payloads exist.

## One-stop analytics solution

`solution` turns a business request into a gated execution manifest. A minimal existing-dataset spec is:

```json
{
  "name": "销售分析体系",
  "datasets": ["456", "789"],
  "busi_type": "dataV",
  "quality": {"mode": "sample", "sample_limit": 200, "fail_on_sensitive": false},
  "metrics": [
    {
      "name": "销售额",
      "definition": "已支付订单含税成交金额，按支付日期统计",
      "dataset_id": "456",
      "field": "销售额",
      "aggregation": "sum",
      "confirmed": true
    }
  ],
  "permissions": [
    {
      "subject_type": "role",
      "subject_id": "100",
      "identity": "销售经理",
      "scope": "datav",
      "resources": [{"id": "$visual", "weight": 7, "ext": 0}]
    }
  ],
  "report": {
    "name": "销售经营周报",
    "rid": "$visual",
    "rtid": "100",
    "rateType": 1,
    "rateVal": "MON 09:00"
  }
}
```

```bash
python scripts/dataease.py solution plan --spec sales-solution.json
python scripts/dataease.py solution execute --spec sales-solution.json
python scripts/dataease.py solution execute --spec sales-solution.json --apply --plan-id plan-xxxxxxxx --confirm-token TOKEN
```

The pipeline is: quality gate → confirmed metric gate → create models → create unpublished visual → grant resources → create report. `quality.mode=sample` computes sample null ratios and full-row duplicates for at most 1000 preview rows. New model IDs can be referenced as `$model:<model name>`, and the created visual as `$visual`. Metrics must have `confirmed: true`; the command refuses inferred business definitions. Composite updates to existing models are deliberately rejected—change them independently with `model save`, then run the solution. On failure, the executor attempts compensating rollback in reverse order and reports any rollback error.

## Version adapter

```bash
python scripts/dataease.py system adapter
```

The adapter currently selects these source-verified families:

| DataEase version | Visual detail | Linkage summary | Plugin API | Dataset native export |
|---|---|---|---|---|
| 2.7.x | legacy GET | without `resourceTable` | unavailable | unavailable |
| 2.8.x-2.9.x | request POST | without `resourceTable` | available | unavailable |
| 2.10.0-2.10.9 | request POST | without `resourceTable` | available | available |
| 2.10.10-2.10.26 | request POST | with `resourceTable` | available | available |

Versions above 2.10.26 use the closest read adapter but mutations are blocked until verified. A controlled compatibility test can opt in with `DATAEASE_ALLOW_UNVERIFIED_VERSION=true`; never enable it by default in production. Versions below 2.7.0 are rejected by this advanced layer.
