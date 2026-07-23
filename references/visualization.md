# Visualization workflow

## Visual spec v2

```json
{
  "schema_version": 2,
  "kind": "dashboard",
  "title": "销售经营分析",
  "theme": "business-light",
  "canvas": {
    "width": 3840,
    "height": 2160,
    "screen_adaptor": true
  },
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
    "filters": ["日期", "大区", "省级行政区", "城市"],
    "filter_cascades": [["大区", "省级行政区", "城市"]],
    "linkage": true,
    "drill_hierarchies": [
      {"chart": "各区域销售额", "fields": ["省", "市", "区县"]}
    ],
    "jumps": [
      {"chart": "各区域销售额", "url": "https://example.invalid/detail", "target": "_blank"}
    ]
  }
}
```

`kind` accepts `dashboard` or `dataV`. Built-in themes are `business-light`, `minimal-light`, `neon-dark`, `deep-ocean`, `dark-gold`, `tech-blue`, `chinese-red`, `government-blue`, `medical-health`, `energy-green`, and `retail-vibrant`. Optional `canvas` accepts a 320–16384 pixel width/height and `screen_adaptor`; DataV pixel geometry is recalculated for that target size, while dashboards retain their responsive grid. Configure a local background with `DATAEASE_BACKGROUND_IMAGE`; it is embedded into the canvas as a data URI.
If the optional background file is missing, the engine reports a warning and safely falls back to the theme color.

Use a custom or corporate-brand theme when a built-in theme is insufficient:

```json
{
  "theme": {
    "base": "corporate-brand",
    "name": "FIT2CLOUD 品牌主题",
    "logo": "assets/company-logo.png",
    "background": "#071A3D",
    "text": "auto"
  }
}
```

Allowed custom fields are `base`, `name`, `accent`/`primary`, `background`, `text`, `colors`, `logo`, `background_image`, and `dark`. `colors` requires at least three `#RRGGBB` values. PNG/JPG assets use local Pillow quantization; SVG assets use their declared colors. Assets are never uploaded for palette extraction. An explicit brand color derives a harmonious five-color chart palette when `colors` is omitted. `text: "auto"` chooses the higher-contrast light/dark foreground; a low-contrast explicit text color is corrected and reported in the resolved theme metadata.

The `visual create` dry-run validates the theme and writes three self-contained SVG previews under `output/theme-previews`: the selected theme, a title-inferred industry theme, and a contrasting alternative. The dry-run response returns each preview path and fully resolved palette. Review or open these files, set the chosen `theme`, then apply the unchanged plan. Preview generation does not create a DataEase resource.

Dashboard and DataV use the same resolved theme contract. DataV additionally applies the palette to fixed-canvas component borders, indicator values/names, map series, line/area series, pie labels and legends, table headers/cells, axes, tooltips and VQuery controls. Explicit DataV canvas dimensions remain authoritative and every smart-grid layout is converted to matching pixels. A transient empty preview caused by an interrupted/chunked frontend response receives one bounded retry; a second failure, a mounted-but-invalid canvas, missing query controls or failed chart-data call still fails verification and triggers compensating cleanup during create.

`interactions.filters` creates a real `VQuery` component bound to authoritative dataset-field metadata. Its conditions carry the complete dataset field catalog and its component envelope includes DataEase's native visibility, category, event and background fields. `filter_cascades` declares ordered, same-dataset query cascades; when omitted or set to `"auto"`, the planner safely groups and orders unambiguous geography, product and organization hierarchy fields such as 大区→省→市, independent of their source-field order or adjacency. Set it to `false` to force parallel filters. Custom business hierarchies must be explicit. The generated native cascade DTO binds each level to its real query-condition and field IDs.

Query styling is background-aware. The planner calculates the canvas background luminance and writes a complete native `VQuery.customStyle.component`: dark canvases receive light labels/placeholders, translucent dark inputs and high-contrast borders; light canvases receive dark labels and white inputs. The query button inherits the active theme accent.

Browser verification requires both a visible `.v-query-container` and at least the requested number of visible `.query-item` controls; a saved but blank query component fails creation and triggers compensating cleanup. `linkage` automatically links only chart views from the same dataset that share an x-axis field. `drill_hierarchies` enables field-level drill metadata, and `jumps` writes an explicit URL event. Cross-dataset cascades/linkage, arbitrary SQL relationships and page-to-page parameter contracts are never guessed.

`dataset plan` can emit a v2 spec from several datasets. Each chart still binds to one DataEase dataset; `dataset_relationships` are review candidates, not executed joins. The semantic layout planner classifies KPI, trend, composition, ranking, comparison and detail components. It places KPI cards first, gives trends more width, uses composition charts as companions and reserves full-width bottom rows for detail tables. Dashboard uses the generated responsive 72×36 grid; DataV also receives matching canvas pixels. Custom `layout` values remain authoritative, and grid-only DataV layouts are completed without replacing explicit pixels.

High-density dashboards are not compressed into an unreadable 1080-pixel canvas. `constraint-v3` estimates each component's minimum/preferred/maximum width and content-derived minimum/preferred height from its rendered title width, axes, dimensions, measures and optional `data_density.category_count/series_count/legend_items/row_count`. It then packs the complete 72×36 grid, allocates row height against per-row minimums and rejects collisions or out-of-bounds geometry. Missing preview statistics are explicitly treated as a metadata estimate. When no explicit dashboard height is supplied, the saved dashboard grows vertically; capture uses that saved size. DataV keeps its fixed target resolution. If its requested content cannot meet readable pixel sizes, dry-run returns `quality.ready=false` with a machine-readable recommendation, and apply refuses creation instead of silently publishing a cramped screen. Reduce components, increase the target DataV resolution, or choose a scrollable dashboard; the Skill never changes the requested resource type silently.

Visual hierarchy is also deterministic. Autopilot limits headline KPI cards, preserves at most two detail-oriented components, balances analytical roles and keeps dataset identity in `source_label` instead of repeating long dataset names in every visible title. The quality gate rejects excessive KPI density, repeated titles, too many detail tables and widespread long titles. On dense dark canvases, component borders, corner radius, padding and glass effects are automatically softened so decoration does not compete with the data.

Field channels are adapter-driven rather than limited by captured template placeholders. Multi-series bar, line, area, scatter and radar charts dynamically construct every declared `y_axis` field; candlestick charts preserve four OHLC measures. Pivot tables keep dimensions in `xAxis` and measures in `yAxis`, while normal detail tables intentionally flatten columns. Bubble maps place the second measure in `extBubble`. Every adapter declares its supported measure count, and payload creation fails when a field is unsupported or missing from the final native channel instead of silently dropping it.

Typography uses the same component geometry instead of one canvas-wide font size. Every chart receives an independent title, legend, axis, label, indicator and table-cell budget. Long titles are compacted for display while the full title is retained in title metadata. User intent remains authoritative:

```json
{
  "canvas": {
    "width": 1920,
    "height": 1080,
    "typography": {
      "mode": "presentation",
      "scale": 1.1,
      "compact_titles": true
    }
  },
  "charts": [
    {
      "type": "bar",
      "data_density": {
        "category_count": 24,
        "series_count": 4,
        "legend_items": 4
      },
      "layout_constraints": {
        "min_width": 36,
        "preferred_width": 48,
        "preferred_height": 300
      }
    }
  ]
}
```

Use `typography.mode` values `auto`, `dense`, `compact` or `presentation`; optional `scale` is bounded to `0.75–1.5`. A per-chart `typography` object overrides the canvas policy. Do not invent density numbers when preview data is unavailable: omit `data_density` and let the solver report `metadata-estimate`.

The planner classifies ID/code fields as identifiers instead of summable measures. Identifier-only datasets use `count_distinct` as an explicit fallback, while rate, ratio, percentage and average fields prefer `avg`; each chart carries aligned `y_aggregations`, and the visual engine writes those values into the DataEase view DTO. All generated KPI definitions remain candidates until their business meaning and aggregation are confirmed.

Chart creation binds the complete authoritative dataset-field DTO (`originName`, `dataeaseName`, `deType`, `groupType`, datasource/table IDs and related metadata) into every rendered axis occurrence. Do not rename template fields without replacing this metadata: DataEase marks mismatched fields red and later edits may drop them.

The v2.10.25 adapter catalog supports 32 callable names across indicator/gauge, line/area, bar variants, pie variants, detail/normal/pivot/heat tables, regional/bubble/flow/heat/symbol maps, scatter, funnel, radar, treemap, word cloud, candle and waterfall. `table_info` is retained as a compatibility alias for native `table-info`. Flow maps require origin and destination as the first two `x_axis` fields. Each adapter writes the native DataEase `type`, `render` and `category` and retains authoritative field DTO binding. This is the Skill's common-chart set, not every chart exposed by DataEase; unsupported types fail before mutation.

For regional map families, province/city/county/district semantics select DataEase's China country map (`id=156`, `level=country`). Longitude/latitude symbolic maps retain the world/coordinate configuration. A successful map data request is not treated as visual success when the required administrative map scope is absent.

Automatic planning publishes both `supported_chart_types` and the narrower `auto_plannable_chart_types`. It creates KPI indicators, line trends, stacked areas for multiple measures, bars and horizontal rankings, donut composition, regional/bubble maps, detail and pivot tables. Two measures enable scatter candidates; three measures enable radar candidates; multiple dimensions enable treemaps; stage/status fields enable funnels; keyword/tag fields enable word clouds. Gauge, candle and waterfall still require recognizable semantic patterns. A 12-component per-dataset profile budget prevents chart proliferation. Types outside `auto_plannable_chart_types` remain explicit-only.

Automatic linkage is limited to views from the same dataset with a common dimension. Drill fields can be inferred from recognized geography/product/organization hierarchies or provided explicitly. Jump targets are never guessed and require a URL. Interaction rules accept either `source` or the compatibility alias `chart` as the chart-title selector.

## Editing an existing resource

Use `visual inspect` to obtain real component/view IDs and field bindings, then `visual patch` for component geometry, style, visibility, view filters/styles, axis field replacement, VQuery `cascade_updates` and canvas theme/layout. The patch engine preserves all unspecified canvas data, blocks identity-field overwrites, resolves replacement fields from DataEase metadata, rebuilds cascade compound IDs from current conditions, snapshots the original resource and rejects stale plans. Never patch raw `cascade` JSON. Use `visual linkage` for the separate server-side linkage DTO lifecycle. Full examples are in [advanced.md](advanced.md).

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

Creation is not considered successful merely because `saveCanvas` returned `code=0`. The apply workflow reads the saved canvas back, executes a real `/chartData/getData` request for every non-query view, confirms publish state, opens the published preview in Chromium and returns both the preview URL and screenshot/PDF path. If chart-data validation or capture fails, a newly created resource is removed through compensating cleanup so a broken dashboard is not left behind.

Query components use the same native compatibility envelope as chart components, including `events.jump`, `commonBackground` and `matrixStyle`. This is required by DataEase's canvas history adaptor; omitting those nested objects can make an otherwise valid saved canvas fail before `.canvas-container` is mounted.

After creation, confirm:

1. The resource appears in the expected organization and business tree.
2. Publish status is correct.
3. Every non-query view passes its real chart-data request.
4. The published preview mounts a visible canvas with no loading masks or unfinished report loads.
5. Text, legend, axis, map and table content are visibly non-empty and not clipped.
6. The returned preview URL opens and the capture artifact exists.

API success and canvas visibility are necessary but not sufficient for visual acceptance. Blank maps, compressed plots or empty table bodies must be reported as quality failures even if their data endpoints return successfully.
