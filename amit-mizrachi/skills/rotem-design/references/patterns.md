# rotem-design: pattern values

The token values behind each rule in `../SKILL.md`. Paths are relative to `apps/dreamteam-io-client/src/`; `CD/` = `components/connections-view/connectors-directory/`. Each value names the shipped file it was read from, so check that file when a value looks wrong: the file wins.

## Layout

- **Settings page**: one header row (title left; search 260px + one main action right), description under the row, content in a centred 1000px column drawn as side padding, never under 40px. `styled-mixins/settings-column-mixin.js`, `CD/connectors-directory-component-styles.ts`.
- **Catalog**: 2-column card grid, gap 16, 1 column under 720px. Every card 88px tall, so the grid stays even. Sections 32px apart, 28px under the page title, section title 16 semibold with a 1px rule 12px under it. `components/settings-catalog-card/settings-catalog-card-styles.ts`.
- **Card**: Shapes UI `Card`, row, gap 16, padding 20, hover `var(--muted)`; 44x44 logo tile (1px `var(--border)`, radius 10, logo 26x26); name 16/24 500; description 14/20 `var(--muted-foreground)`; both one line with ellipsis; status control on the right.
- **Detail page**: ghost `icon-sm` back arrow + 16/24 500 name bar; header with 64px logo tile radius 16, title 24/32 600, muted description, status, ONE action on the right; rule under the header; body a 2-column grid, gap 32px 48px, 1 column under 900px. A block that belongs to the whole page spans both columns (`grid-column: 1 / -1`) above the grid. `CD/connector-page/connector-page-component-styles.ts`.
- **Menu list**: width 320; rows 44px (8 + 28 tile + 8), gap 2, radius 10, hover `var(--muted)`; stop at 5.5 rows so the cut row says "more below", scrollbar hidden; search appears past seven items. `connections-view/mcp-connections-menu/connectors-panel-component-styles.js`.
- **Framed rows in a dialog**: each item a row, padding 10px 12px, 1px border, radius 10, its action inside the row. `features/vibe/vibe-connect-popup/vibe-connect-popup-component-styles.ts`. For a list of rows inside one frame: frame padding 4, gap 2, row radius 6 (10 - 4).
- **Window clearance**: nothing within 56px of the window X (`os.window.CLOSE_BUTTON_CLEARANCE`); page header rows centre 42px below the window top (`os.window.TOP_ROW_CENTER`, `styled-mixins/top-row-mixin.js`).
- **Geometry from neighbours**: derive a position from the element beside it and write the sum (`left: calc(50% + 40px)` = half the 80px rail; `RAIL_WIDTH = 12 + 32 + 12`).

## Spacing

Scale: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64.

| Gap | Use |
|---|---|
| 2 | tight list rows, title to description |
| 4-6 | list items inside a dialog |
| 8 | buttons in a row, list items, chips |
| 10 | tile to name in a row |
| 12 | header to body, rule to content |
| 16 | card inner gap, grid gap, dialog sections |
| 32 | between page sections |

Paddings: card 20, dialog 24, dialog footer 14px 24px, note 12, row 8, page bottom 80. Measure optical gaps to the letters, not the box: a mark sits 13px from its title's letters with `margin-bottom: 1px` to absorb half-leading.

## Radius

Concentric: inner = outer - padding (Home prompt card 20, padding 6, inner field 14).

| Radius | Use |
|---|---|
| 6 | small X button, rows inside a 4px-padded frame |
| 8 | dialog, 28px and 32px logo tiles, tooltip, pills, notes in a dialog |
| 10 | 44px logo tile, menu rows, framed rows, page notes |
| 12 | Vibe popup, quick links |
| 16 | 64px logo tile, video hero |
| 20 | Home widgets and prompt |

## Type

Geist for all UI; Crimson Pro only for display headlines, greetings and playful empty-state lines. Type mixin: `styled-mixins/typography-mixin` `typographyMixin[types.<NAME>]`.

| Role | Value |
|---|---|
| Settings page title | `GEIST_HEADING_S_MEDIUM` (24/32 500) via `settingsPageTitleMixin` |
| Dialog title | 24/32 500 (connect step) or 22px 600 (popup) |
| Detail page title | 24/32 600 |
| Section title | 16/24 600 |
| Card name | 16/24 500 |
| Row name | 14/20 500 |
| Body, description | 14/20 regular, `var(--muted-foreground)` (`GEIST_BODY_XS_REGULAR`) |
| Label over a list | 14/20 500 muted (`GEIST_BODY_XS_MEDIUM`) |
| Caption, empty line in a menu | 12/16 muted |

Going a size smaller reads calmer (quick links 16 -> 14). Single-line text: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`.

## Colour

- New surfaces: `var(--foreground)` names, `var(--muted-foreground)` descriptions, labels and icons, `var(--muted)` hover fill and notes, `var(--border)` 1px tiles and frames, `var(--background)` tile fill, `var(--ring)` focus, `var(--primary)` (the Switch's own on colour).
- Connected tint: `color-mix(in srgb, var(--success) 22%, var(--background))` border, 9% fill, 15% hover. `CD/connector-trust/connector-trust-components-styles.ts`.
- Legacy surfaces keep clay tokens from `constants/colors`: `brown-100` titles, `brown-80` body, `brown-40` frames, `gunmetal` tooltip.
- Raw `rgba()` only for: backdrop `rgba(0,0,0,0.5)`, dialog shadow `0 3px 12px 1px rgba(0,0,0,0.06)`, the agent glow (the app's accent at 0.1).
- One accent per page or app. A state that is not an error (a missing grant, an optional step) uses neutral text and a Connect button.

## Icons

Tabler only (`@tabler/icons-react`): 16px in text rows (muted, `margin-top: 2px`), 20px in buttons. Brand logos come from `icons/connectors/<name>.svg` inside a bordered tile.

| Meaning | Icon |
|---|---|
| connect / add | `IconPlus` |
| connected (in the square) | `IconCheck stroke={2.5}` |
| "Connected" status text | `IconCircleCheck` in `var(--success)` |
| what it reads | `IconEye` |
| access or privacy note | `IconLock` |
| overlap or info note | `IconInfoCircle` |
| verified seal (muted: a mark, not a control) | `IconRosetteDiscountCheck` 16px |
| menu button | `IconChevronDown data-icon="inline-end"` |
| back | `IconArrowLeft className="rtl:rotate-180"` |
| close | `IconX` |

## Motion

- Hover and press 100ms; tone change 200ms ease; colour fade between pages 700ms; a deliberate turn 640ms `cubic-bezier(0.65, 0, 0.35, 1)`.
- Every animation has a `@media (prefers-reduced-motion: reduce)` branch.
- An animation finishes once started; a new trigger waits for it.
- Heights stay fixed while content changes (suggestions live inside a fixed-height prompt; a status pill sits beside the composer, outside its height).
- An effect that glitches in a browser (Chrome redrawing `backdrop-filter` in strips) is removed.

## Copy

- Sentence case, short. Buttons verb + object: "Connect {name}", "Disconnect", "Cancel", "Not now", "See guide".
- Dialog title: a short question naming the thing, one line beside its logo: "Connect {name}?", "Remove {name}?".
- Destructive confirm: secondary "Keep {name}" (outline), primary "Remove" (`variant="destructive"`). The body says who loses what and what stays.
- States one word: "Connected". Hints state + action: "{name} is connected. Click to disconnect".
- Toasts: "Jira connected", with no "successfully" and no full stop.
- Privacy in concrete terms: "The agent reads with each person's own access in {name}, so it only sees what they can already open."
- Section labels plain: "What HR uses it for", "What the agent can read". A card description says what HR uses the thing for, not a list of its parts.
- Empty search: "No connectors match "{query}"".
- Greet by first name only on Home; other screens get a plain line.

## States

- **Empty**: a centred 14px muted line with 64px padding. On Home: a playful illustration and a Crimson Pro italic line.
- **Loading or working**: the agent mark morphs, in an element with `role="status"` and a name ("Generating your view"). Thinking is one line: small mark + current step.
- **Error**: a calm note, said once: the mark in red with a white X, a short centred apology, announced to screen readers.
- **Disabled**: keeps a tooltip that says why.
- **Hover**: `var(--muted)` fill on cards and rows; muted icons turn `var(--foreground)`; the hover square sits on the real click target only.
- **Focus**: `:focus-visible` 2px `var(--ring)` outline, offset 2; consent and connect dialogs focus the primary action, a destructive confirm leaves focus on the cancel ("Keep {name}") and never focuses the destructive action.
- **Connected**: the green-tinted square (card) or "Connected" pill (menu row), opening a menu with a destructive remove item.

## Groups and choices

| Situation | Pattern |
|---|---|
| A catalog of many things | Sections by what HR uses them for, connected first, 2-col card grid |
| On/off per item | `Switch` per row, the row a `<label>` with `cursor: pointer` |
| A few items to act on in a dialog | Framed rows, the action inside each row |
| One item | No picker: the dialog names that item in title, logo and button |
| A choice of what to add | `Button` + `IconChevronDown` opening a `DropdownMenu` |
| Status that is also a control | Outline icon button (plus / tinted check) with a hint |
| Consent | The primary button; no checkbox |
| Suggestions | Up to 3 short chips |
