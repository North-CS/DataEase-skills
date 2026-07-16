# Visualization workflow

## Visual spec v1

```json
{
  "schema_version": 1,
  "kind": "dashboard",
  "title": "销售经营分析",
  "theme": "business-light",
  "charts": [
    {
      "type": "bar",
      "title": "各区域销售额",
      "dataset_name": "数据集名称或 ID",
      "x_axis": ["区域"],
      "y_axis": ["销售额"]
    }
  ],
  "interactions": {
    "filters": ["日期", "区域"],
    "linkage": true
  }
}
```

`kind` accepts `dashboard` or `dataV`. `theme` accepts `business-light` or `neon-dark`. Configure a local background with `DATAEASE_BACKGROUND_IMAGE`; it is embedded into the canvas as a data URI.
If the optional background file is missing, the engine reports a warning and safely falls back to the theme color.

The template-backed create engine currently supports `bar`, `line`, `pie`, and `table_info`. Capability metadata may advertise additional DataEase chart types, but do not use them for creation until a tested template adapter exists.

## Selection rules

- Use line charts for time trends.
- Use bars for category comparison or ranking.
- Use pies only for a small number of meaningful categories.
- Use tables for detail and reconciliation.
- Do not infer business KPI definitions solely from numeric types.
- Check sensitive fields before placing them in tables.

## Dashboard versus DataV

- Use `dashboard` for analysis, responsive layout and frequent interaction.
- Use `dataV` for fixed-resolution command-center displays and visual themes.
- Use absolute pixel positions for DataV and grid positions for dashboards.
- Capture the published result at its intended display resolution.

## Verification

After creation, confirm:

1. The resource appears in the expected organization and business tree.
2. Publish status is correct.
3. Every chart renders with non-empty axes and no API errors.
4. Text, legend, axis and table content are not clipped.
5. The returned preview URL opens and the capture artifact exists.
