# Visualization workflow

## Visual spec v2

```json
{
  "schema_version": 2,
  "kind": "dashboard",
  "title": "销售经营分析",
  "theme": "business-light",
  "charts": [
    {
      "type": "bar",
      "title": "各区域销售额",
      "dataset_name": "数据集名称或 ID",
      "x_axis": ["区域"],
      "y_axis": ["销售额"],
      "layout": {
        "x": 1,
        "y": 1,
        "sizeX": 36,
        "sizeY": 18,
        "left": 32,
        "top": 32,
        "width": 916,
        "height": 496
      }
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

`dataset plan` can emit a v2 spec from several datasets. Each chart still binds to one DataEase dataset; `dataset_relationships` are review candidates, not executed joins. The semantic layout planner classifies KPI, trend, composition, ranking, comparison and detail components. It places KPI cards first, gives trends more width, uses composition charts as companions and reserves full-width bottom rows for detail tables. Dashboard uses the generated responsive 72×36 grid; DataV also receives matching canvas pixels. Custom `layout` values remain authoritative, and grid-only DataV layouts are completed without replacing explicit pixels.

The planner classifies ID/code fields as identifiers instead of summable measures. Identifier-only datasets use `count_distinct` as an explicit fallback, while rate, ratio, percentage and average fields prefer `avg`; each chart carries aligned `y_aggregations`, and the visual engine writes those values into the DataEase view DTO. All generated KPI definitions remain candidates until their business meaning and aggregation are confirmed.

Chart creation binds the complete authoritative dataset-field DTO (`originName`, `dataeaseName`, `deType`, `groupType`, datasource/table IDs and related metadata) into every rendered axis occurrence. Do not rename template fields without replacing this metadata: DataEase marks mismatched fields red and later edits may drop them.

The template-backed create engine currently supports `bar`, `line`, `pie`, and `table_info`. Capability metadata may advertise additional DataEase chart types, but do not use them for creation until a tested template adapter exists.

## Editing an existing resource

Use `visual inspect` to obtain real component/view IDs and field bindings, then `visual patch` for component geometry, style, visibility, view filters/styles, axis field replacement and canvas theme/layout. The patch engine preserves all unspecified canvas data, blocks identity-field overwrites, resolves replacement fields from DataEase metadata, snapshots the original resource and rejects stale plans. Use `visual linkage` for the separate server-side linkage DTO lifecycle. Full examples are in [advanced.md](advanced.md).

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
