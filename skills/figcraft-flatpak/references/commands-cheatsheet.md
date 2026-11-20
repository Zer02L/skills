# FigCraft Command Cheatsheet (`v0.18.1`)

Load this reference when creating styles, variables/tokens, components/variants, vectors, gradients, prototyping flows, or inspecting generated code.

## Batch step references

- Top-level `run` scripts execute a JSON array `[...]` or JSONL as one undoable script (`--out` saves `.figcraft`).
- `command.batch` wraps multiple steps inside one explicit batch: `{"command": "command.batch", "params": {"label": "...", "onError": "abort", "commands": [...]}}`.
- Name a step `"as": "card"`, then reference its returned `id` with `{"$ref": "card"}` or a nested field with `{"$ref": "copy", "field": "ids/0"}` (or `{"$step": 0}`).

## Layer & shape creation

- `frame.create`: `{preset?, x?, y?, width?, height?, parent?, index?, name?, props?, select?}` (`frame.presets` lists preset names).
- `text.create`: `{text | characters, x?, y?, parent?, index?, name?, width?, props?, select?}` (`width` wraps text).
- `shape.rectangle` / `shape.ellipse`: `{x, y, width, height, parent?, index?, name?, props?, select?}`.
- `shape.polygon` / `shape.star`: `{x, y, width, height, parent?, props? {pointCount, innerRadius?}}`.
- `shape.line` / `shape.arrow`: `{x, y, width (length), parent?, props? {rotation?}}`.
- `vector.create`: `{path (SVG path data) | points [[x,y],..], closed?, x?, y?, width?, height?, parent?, props?}`.
- `image.place`: `{path | data (base64), x?, y?, width?, height?, parent?, name?, target?, mode? (fill|fit|crop|tile)}`.
- `node.create`: `{type: rectangle|ellipse|polygon|star|line|arrow|vector|text|frame|section|component|slice, ...}`.

## `node.set` property keys (also valid inside `props: {...}`)

- **Identity & tree:** `name`, `visible`, `locked`, `opacity` (`0-1` or `"50%"`), `blend`, `x`, `y`, `width`, `height`, `rotation`, `constrainProportions`, `overflow`, `clip`, `isMask`.
- **Paints & strokes:**
  - `fill`: `"#RRGGBB"`, `"#RRGGBBAA"`, `{"$var": "id-or-name"}`, `"none"`, `null`.
  - `fills`: array of colours, `{$var: ...}`, or gradients `{type: "linearGradient"|"radialGradient"|"angularGradient"|"diamondGradient", stops: ["#hex", ...], from?, to?}`.
  - `stroke`, `strokes`, `strokeWeight`, `strokeAlign` (`inside`|`center`|`outside`), `strokeTopWeight`/`Right`/`Bottom`/`Left`, `dashes`.
  - `cornerRadius` (`n` or `[tl, tr, br, bl]`), `cornerSmoothing` (`0-1`), `effects`.
- **Auto-layout & grid:**
  - `layout`: `null` | `"horizontal"` | `"vertical"` | `"grid"`.
  - `gap`, `crossGap` (`columnGap`/`rowGap` aliases), `padding` (`n` or `[t, r, b, l]`), `paddingTop`/`Right`/`Bottom`/`Left`.
  - `mainAlign`: `min` | `center` | `max` | `spaceBetween` | `spaceAround` | `spaceEvenly`.
  - `crossAlign`: `min` | `center` | `max` | `baseline` (not `stretch`).
  - `wrap`, `strokesIncluded`, `reverseZ`, `contentAlign` (`auto` | `spaceBetween`).
  - Child sizing & bounds: `sizingH` / `sizingV` (`fixed` | `hug` | `fill`), `absolute` (bool), `minWidth`, `maxWidth`, `minHeight`, `maxHeight`, `constraints {horizontal, vertical}`.
  - Grid layout: `gridColumns`, `gridRows`, `columnTracks` / `rowTracks` (`[120 | "1fr" | "auto" | {sizing, value}]`), `gridColumn`, `gridRow`, `gridColumnSpan`, `gridRowSpan`, `gridAlignH`, `gridAlignV`.
- **Typography:**
  - `characters`, `fontFamily`, `fontStyle`, `fontSize`, `lineHeight` (`auto`|px|`"150%"`), `letterSpacing` (px|`"2%"`).
  - `textAlign` (`left`|`center`|`right`|`justified`), `textAlignVertical`, `textAutoResize` (`widthAndHeight`|`height`|`none`|`truncate`), `maxLines`, `textCase` (`original`|`upper`|`lower`|`title`|`smallCaps`), `textDecoration`, `paragraphSpacing`, `listStyle` (`none`|`bulleted`|`numbered`).

## Query & code generation

- `node.find`: `{root?, name?, type?, text?, component?, limit?}` → `{ids, total}` (case-insensitive substring match; does not select).
- `node.get`: `{id, fields?: [...], outline?: bool}`.
- `node.reparent`: `{ids?, parent, index?}` | `node.reorder`: `{id, index}`.
- `edit.duplicate`: `{ids?, dx?, dy?, map?: true}` (copies of a main component become instances).
- `inspect.code`: `{id?, language?: css|html|react|leptos|vue|tailwind|swiftui|compose|arkui|flutter, unit?: px|rem, mobile?: frameId}` → `{code, language, connected}`.
- `inspect.properties`: `{id?, colorFormat?: hex|rgb|css|hsl|hsb}`.
- `inspect.assets`: `{ids?}` → `{assets: [{id, name, kind, exports}]}` (export with `file.exportLayers {assets: true}`).
- `inspect.componentCode`: `{id?, language?: react|leptos|vue|swiftui|compose|arkui|flutter}`.

## Styles, variables, components & prototyping

- `style.create`: `{type: "paint"|"text"|"effect"|"grid", name, from?, description?, value?}` and `style.apply`: `{ids?, style, target?: "fill"|"stroke"}`.
- `variable.createCollection`: `{name, modes?: ["Light", "Dark"]}`.
- `variable.create`: `{collection, name, type: "color"|"number"|"string"|"boolean", value | values: {"Light": ..., "Dark": ...}}` (supports `{alias: var}`, `{alpha: {variable, opacity}}`, `{mix: {from, to, t}}`).
- `variable.bind`: `{ids?, field, variable}` (`field`: `fill`, `stroke`, `fills/0/color`, `width`, `height`, `opacity`, `cornerRadius`, `gap`, `paddingHorizontal`, `characters`, `visible`, `fontSize`, ...).
- `component.create`: `{ids?}` | `component.addVariant`: `{id?, property?, value?}` | `component.combineVariants`: `{ids?}` | `component.addProperty`: `{id?, name, type: "boolean"|"text"|"instanceSwap"|"variant"|"slot", default?, layer?}`.
- `proto.interaction.add`: `{id?, trigger?: {type: "onClick"|"onHover"|"onPress"|"onDrag"|"afterDelay"|...}, action?: {type: "navigate"|"back"|"openOverlay"|"closeOverlay"|"changeTo"|"setVariable"|"setVariableMode"|..., dest?}, transition?: {type: "instant"|"dissolve"|"smartAnimate"|"push"|"slideIn", direction?}, durationMs?, easing?}` (or shorthand `{id, dest}`).
- `proto.flow.add`: `{start?, name?}`.

## Supported export & convert formats

- **Import/open:** `.figcraft`, `.penpot`, `.json` (FigCraft / REST API), `.fig` (best effort), `.sketch` (48+, best effort), `.svg`, `.png`, `.jpg`, `.webp`, `.gif`, `.bmp`.
- **Export (`file.export` / `fc.sh export`):** `png`, `jpg`, `svg`, `webp`, `pdf` (supports `bleed`, `cropMarks`, `bleedMarks`, `cmyk`), `xml` (Android Vector Drawable), `fig` (experimental), `penpot`.
