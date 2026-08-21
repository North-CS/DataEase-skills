# Mutation spec guide

Use official DataEase DTO-shaped JSON. Prefer piping secret-bearing specs through standard input. Never commit real credentials or recipients.

## Data source and dataset

### Local CSV/XLSX data source

Use `file-datasource generate` when the Agent has already produced structured data and needs a portable local file. The input is intentionally data-only: it accepts `columns`, `rows`, and an optional `sheet`, rather than an unconstrained natural-language prompt.

```json
{
  "sheet": "销售明细",
  "columns": ["日期", "区域", "销售额"],
  "rows": [
    ["2026-08-01", "华东", 128000],
    {"日期": "2026-08-02", "区域": "华南", "销售额": 93000}
  ]
}
```

Generate the file first, then create a dry-run with `file-datasource create --file <path>`. This command supports UTF-8 CSV and XLSX (not legacy XLS), requires unique non-empty headers, and rejects files over 500 MiB. Its apply stage uploads multipart `file`, `id=0`, and `editType=0` to `/datasource/uploadFile`, selects all returned sheets or explicit `--sheet` values, Base64-encodes the returned sheet configuration, and saves an `Excel` datasource through `/datasource/save`. The file digest is bound to the plan; modifying the file, name, folder, or selected sheets requires a new plan.

Do not upload source files containing unapproved personal, secret, or production data. The create plan stores only file metadata and SHA-256, never rows or file bytes. The upload is an L1 write and should be confirmed before `--apply`. Dataset creation and visual creation are later independent plans because their server-generated table and field identifiers are not available during the no-write dry-run.

Data-source configuration differs by connector and DataEase version. Inspect `datasource types` and an equivalent source's redacted shape before creating one. DataEase `2.10.25` MySQL host-mode was validated with this DTO shape:

```json
{
  "name": "业务库",
  "pid": "0",
  "type": "mysql",
  "configuration": {
    "urlType": "hostName",
    "host": "db.internal",
    "port": "3306",
    "dataBase": "business",
    "username": "...",
    "password": "...",
    "extraParams": "",
    "initialPoolSize": 5,
    "minPoolSize": 5,
    "maxPoolSize": 20,
    "queryTimeout": 30
  }
}
```

The DataEase V2 frontend Base64-encodes connector configuration JSON before calling save/validate. The CLI accepts a JSON object/list and performs that encoding in memory; an already encoded string is passed through unchanged. Do not reuse a configuration shape across connector types. `datasource update` is L3 because the old connection secret cannot be recovered from `hidePw`.

Dataset create/save uses DataEase `DatasetGroupInfoDTO`. Folder creation has a dedicated command and does not require a spec. For a `2.10.25` physical-table dataset, use the exact datasource/table metadata and fields returned by `/datasetData/tableField`:

```json
{
  "nodeType": "dataset",
  "name": "销售明细",
  "pid": "0",
  "isCross": false,
  "union": [
    {
      "currentDs": {
        "tableName": "sales",
        "type": "db",
        "datasourceId": "123",
        "id": 456,
        "info": ""
      },
      "currentDsFields": [],
      "childrenDs": [],
      "unionToParent": {"unionType": "left", "unionFields": []}
    }
  ],
  "allFields": []
}
```

Preserve the response types for the table node `id`, `datasourceId`, fields and `info`; replace `currentDsFields` and `allFields` with the returned field objects rather than hand-written approximations. Do not reuse this shape for SQL, API, Excel or cross-source datasets.

Use the discovery commands instead of manually constructing those DTOs:

```bash
python scripts/dataease.py datasource tables --datasource-id 123
python scripts/dataease.py datasource table-fields --datasource-id 123 --table-name sales
```

Some `2.10.x` servers return `info: null` and `isCross: null` from `getTables` even though `tableField` requires a serialized `{"table":"..."}` descriptor and a concrete boolean. The Skill fills those two missing physical-table values (`info` and `isCross: false`) and otherwise preserves the server DTO unchanged.

## Data filling

Bind a form to a DataEase datasource and an existing physical table with the official
`DataFillingDTO` fields. `forms` is the DataEase form-designer JSON string; obtain a known-good
shape from an equivalent form rather than inventing component DTOs.

```json
{
  "name": "销售目标填报",
  "pid": "0",
  "nodeType": "form",
  "datasource": "123",
  "datasourceName": "业务数据库",
  "tableName": "sales_target_input",
  "useExistsTable": true,
  "forms": "[]",
  "createIndex": false,
  "tableIndexes": "[]"
}
```

Use `filling datasources` to list eligible sources. `filling built-in-tables` lists tables from
DataEase's built-in datasource; use the general `datasource tables` command for an external
datasource. A scheduled task uses `rateType`, `oneTimeType`, `rateVal`, `startTime` and `endTime`.
Inspect an equivalent task because the exact `rateVal` representation depends on the selected
schedule type and DataEase version. `task-stop` cancels future scheduling without deleting the
definition; `task-start` resumes it. `task-execute-now` triggers one run. `task-delete` permanently
removes the task definition.

## Administration

```json
{
  "name": "数据分析组织",
  "pid": "0"
}
```

```json
{
  "name": "数据分析员",
  "typeCode": 0,
  "desc": "只授予所需权限"
}
```

```json
{
  "name": "张三",
  "account": "zhangsan",
  "email": "zhangsan@example.invalid",
  "phone": "",
  "roleIds": [123],
  "enable": true,
  "mfaEnable": false,
  "variables": []
}
```

On DataEase `2.10.25`, `/user/create` iterates `variables` without accepting null. The Skill supplies `variables: []` and `mfaEnable: false` when callers omit them, and binds that normalized DTO to the plan digest. The DTO has no password field and the server always assigns its configured initial password. The Skill rejects `password`, `pwd`, `newPwd` and similar fields before planning; it never pretends a caller-supplied password was applied and never persists that value.

Use the current detail payload as the base for edit operations and preserve fields not intentionally changed.

Role safety is derived from live DataEase metadata, not the role's displayed name. Creating a user with an administrator role (`root=true`, `readonly=false`), changing a user's normalized `roleIds`, running `role-edit`, or changing a role permission matrix produces an L3 plan and requires its confirmation token. Creating an ordinary user remains L1; editing non-role user fields remains L2.

`role-edit` changes only role metadata (`name` and `desc`). Use `role-permission-set` for one role's independent menu/resource permission matrix, or `permission apply` for a multi-scope user/role resource bundle. The permission spec is strict so misspelled keys are rejected before DataEase can silently ignore them:

```json
{
  "roleId": 123,
  "scope": "dataset",
  "permissions": [
    {"id": 456, "weight": 3, "ext": 0}
  ]
}
```

Supported scopes are `menu`, `panel`, `screen`, `datasource`, `dataset`, and `data_filling`; `dashboard` and `datav` are accepted aliases for `panel` and `screen`. The array is the complete desired direct-permission matrix and accepts weights `1`–`9`. Remove an existing resource from the array to revoke it; the Skill compares the current matrix and sends only changed entries, including DataEase's required incremental `weight: 0` revocation. Read the current matrix before editing. `role-permission-set` snapshots the selected scope and verifies readback after apply, but rollback remains an explicit operator action. It rejects embedded row/column rules because those have a separate lifecycle; use `model permission-list/save/delete` with the official row/column permission DTO. If the current DataEase edition/version lacks the permission endpoints, configure the matrix through the UI instead of assuming `role-edit` changed it.

Component-edit, dataset-model, portable-restore, plugin package and end-to-end solution specs are documented in [advanced.md](advanced.md). Preserve DTOs from the target DataEase version; the advanced commands validate structure but cannot invent join keys, business metric definitions, row filters or extension metadata.

## Settings

Settings are arrays of key/value records:

```json
[
  {"pkey": "basic.frontTimeOut", "pval": "300", "type": "text", "sort": 1}
]
```

Read the entire current scope first, change only intended `pval` values, and submit the complete expected list. Authentication scopes are L3.

The pkey set must exactly match the current scope and contain no duplicates. DataEase `2.10.25` email save is blocked by the Skill after live testing found that the official endpoint can append duplicate settings; `admin setting-validate --scope email` is the supported safe path for that version.

## Platform integrations

DingTalk:

```json
{
  "corpId": "...",
  "agentId": "...",
  "appKey": "...",
  "appSecret": "...",
  "callBack": "https://dataease.example.com",
  "enable": false,
  "valid": false,
  "robotCode": "...",
  "chatList": []
}
```

WeCom uses `corpId`, `agentId`, `appSecret`, `callBack`, `enable`, and `valid`. Lark/Larksuite use `appId`, `appSecret`, `callBack`, `enable`, and `valid`.

Keep `enable` false until `integration-validate` succeeds and the provider callback URL is reachable. Saving or toggling an integration is L3.

## SSO

LDAP, OIDC, CAS, OAuth2 and SAML2 each have different official DTOs. Start with:

```bash
python scripts/dataease.py admin sso-info --provider oidc
```

Preserve the returned non-secret fields, add credentials through secure input, run `sso-validate`, then use the same spec for `sso-save`. Do not enable SSO until a separate local administrator login has been verified.

## Scheduled report

This is a complete structural example. Replace resource IDs, schedule and recipients deliberately:

```json
{
  "name": "经营周报",
  "title": "经营周报",
  "content": "请查收本周经营数据。",
  "rtid": 0,
  "rid": "123",
  "showWatermark": false,
  "format": 0,
  "viewIdList": [],
  "viewDataRange": 1,
  "pixel": "1920 * 1080",
  "reciFlagList": [1],
  "uidList": [],
  "ridList": [],
  "emailList": ["recipient@example.invalid"],
  "dingtalkGroupList": [],
  "larkGroupList": [],
  "larksuiteGroupList": [],
  "extWaitTime": 0,
  "rateType": 1,
  "rateVal": "2021-08-01 09:00:00",
  "startTime": 1893456000000,
  "endTime": 1924992000000,
  "retryEnable": false,
  "retryLimit": 3,
  "retryInterval": 5,
  "reportFilter": [],
  "dataPermission": 0
}
```

`rtid` is `0` for a dashboard and `1` for DataV. Report creation, update, start and fire-now are L3 because they can transmit data externally.

## Webhook

```json
{
  "name": "告警入口",
  "url": "https://hooks.example.invalid/dataease",
  "secret": "...",
  "contentType": "application/json",
  "ssl": true,
  "msgTemplate": "{\"event\":\"${event}\",\"content\":\"${content}\"}"
}
```

For update, include `id`. Public results return only endpoint scheme/host/port. The full URL and secret remain private.
