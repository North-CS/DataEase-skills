# Mutation spec guide

Use official DataEase DTO-shaped JSON. Prefer piping secret-bearing specs through standard input. Never commit real credentials or recipients.

## Data source and dataset

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
  "enable": true
}
```

Use the current detail payload as the base for edit operations and preserve fields not intentionally changed.

Role safety is derived from live DataEase metadata, not the role's displayed name. Creating a user with an administrator role (`root=true`, `readonly=false`), changing a user's normalized `roleIds`, or running `role-edit` produces an L3 plan and requires its confirmation token. Creating an ordinary user remains L1; editing non-role user fields remains L2.

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
