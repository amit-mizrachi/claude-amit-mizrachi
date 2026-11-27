# rotem-design: components and source files

Paths are relative to `apps/dreamteam-io-client/src/` in shapes-platform unless they say otherwise; `CD/` = `components/connections-view/connectors-directory/`. Shapes UI source: `packages/shapes-ui/src/components/ui/<name>.tsx`. Read the source for props before you use a component; the facts below were true when this skill was written.

## @shapesos/ui components to reach for

Import from `@shapesos/ui/<name>` (never from `/src`). Restyle with a styled-components wrapper that uses `&&` for specificity.

| Need | Import | Facts |
|---|---|---|
| Buttons | `import { Button } from "@shapesos/ui/button";` | `variant`: default (dark), outline, secondary, ghost, destructive (light red fill), link. `size`: default, xs, sm (h-7), lg, icon (32), icon-xs (24), icon-sm (28), icon-lg (36). Icon in a button: `data-icon="inline-start"` or `"inline-end"`. |
| On/off | `import { Switch } from "@shapesos/ui/switch";` | `checked`, `onCheckedChange(checked)`, `size` `"sm"` (24x14, for dense rows and dialogs) or `"default"` (32x18), `disabled`, `aria-label`. Add `cursor: pointer` in the wrapper. |
| Confirm and consent dialogs | `import { AlertDialog, AlertDialogAction, AlertDialogCancel } from "@shapesos/ui/alert-dialog";` | Restyle `AlertDialogContent`, `AlertDialogTitle`, `AlertDialogFooter`. `AlertDialogAction variant="destructive"` for remove. A `ref` on the primary action for initial focus. |
| Menus | `import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@shapesos/ui/dropdown-menu";` | `DropdownMenuItem variant="destructive"` for Disconnect or Remove behind a status control. |
| Cards | `import { Card } from "@shapesos/ui/card";` | Use it through `CatalogCard` in `components/settings-catalog-card/settings-catalog-card-styles.ts` (`size="sm"`). |
| Search | `@shapesos/ui/input-group` (`InputGroup`) | 260px in a settings header row. |
| Hints | `HintComponent` from `components/settings-catalog-card/hint-component.tsx` | Wraps `@shapesos/ui/tooltip`, restyled to the app tooltip (8px 14px, 14/20, radius 8, gunmetal). Props `label`, `side`. |
| Beta badge | `BetaBadgeComponent` from `components/beta-badge/beta-badge-component` | `isCompact` beside a title. |
| Icons | `@tabler/icons-react` | See `patterns.md` Icons. |

`@shapesos/ui/item` (`Item`, `ItemMedia`, `ItemActions` ...) exists, but no Rotem surface uses it: her rows are local styled divs. Copy the panel row anatomy instead.

`checkbox` exists and reads as a form; her per-item on/off is a `Switch`.

Every `@shapesos/ui` component is a draft in `packages/shapes-ui/component-status.json`, so the `shapes-ui/no-draft-components` lint rule warns on each import. That warning is already on main for her surfaces; it is not a blocker. Only a designer approves a component.

## Connectors v2: the reference implementation

Rotem's Connectors v2 (shapes-platform PR https://github.com/dreamteamapp/shapes-platform/pull/3670) is the most complete example of every pattern in this skill. Read these files when you need a working example.

| Pattern | File | What to look at |
|---|---|---|
| Catalog card + grid | `components/settings-catalog-card/settings-catalog-card-styles.ts` | Grid L9-17, card L22-40, logo tile L42-58, name and description ellipsis L75-92 |
| Directory page frame | `CD/connectors-directory-component-styles.ts` | Title row L33-40, search 260px L56-59, sections and rules L63-81, empty search L96-101 |
| Card row and status control | `CD/connectors-directory-component.tsx`, `CD/connector-trust/connector-trust-components.tsx` | `ConnectorRow`; `ConnectorStatusButtonComponent` (outline square, tinted check, destructive menu item) |
| Connected tint | `CD/connector-trust/connector-trust-components-styles.ts` | `color-mix` success tint L18-30, verified seal L4-14 |
| Connect step dialog | `CD/connect-consent/connect-consent-dialog-component-styles.ts` | Backdrop scope L19-24, content 480 L26-36, header L39-73, sections and eye list L76-121, note L124-130, footer L132-143 |
| Destructive confirm | `CD/disable-confirm/disable-connector-dialog-component.tsx` | Same dialog styles, "Keep {name}" + destructive action |
| Detail page | `CD/connector-page/connector-page-component-styles.ts` | Header L39-108, body grid L114-123, sections and notes L125-180 |
| Menu panel rows with Switch | `connections-view/mcp-connections-menu/connectors-panel-component-styles.js` | `Row`, `Icon` (28 tile radius 8), `Logo` 18, `Name`, `ConnectedButton` pill |
| Menu panel component | `connections-view/mcp-connections-menu/connectors-panel-component.js` | `ConnectorRow`: Connect is the same `Button size="sm"` as the chat Connect card, so Connect looks alike everywhere |
| Settings mixins | `styled-mixins/settings-column-mixin.js`, `styled-mixins/settings-page-title-mixin.js` | 1000px column, page title type |
| Copy | `translations/en.json`, keys `connectorsDirectory.*` | Titles, buttons, hints, empty state, safety copy |

## Other surfaces by Rotem worth copying

| Surface | PR | File |
|---|---|---|
| Popup drawn as the app's modal, framed rows | https://github.com/dreamteamapp/shapes-platform/pull/4267 | `features/vibe/vibe-connect-popup/vibe-connect-popup-component-styles.ts` |
| Release popup reusing a known layout | https://github.com/dreamteamapp/shapes-platform/pull/4337 | `components/shapes-ai-release/shapes-ai-release-component-styles.ts` |
| Concentric radii, smaller calmer quick links | https://github.com/dreamteamapp/shapes-platform/pull/4338 | `home-prompt/home-prompt-component-styles.ts`, `home/action-card/action-card-component-styles.js` |
| Motion with reduced-motion branch, geometry from the neighbour | https://github.com/dreamteamapp/shapes-platform/pull/4384 | `app-agent-panel/app-agent-trigger-button-component-styles.ts` |
| Content-driven wrapping, before/after screenshot table | https://github.com/dreamteamapp/shapes-platform/pull/2193 | Home quick links |
| Measured before/after tables in the PR body | https://github.com/dreamteamapp/shapes-platform/pull/4582, https://github.com/dreamteamapp/shapes-platform/pull/4628 | `app-agent-panel/constants.ts` |
| One accent per app, optical spacing | https://github.com/dreamteamapp/shapes-platform/pull/4632 | `features/vibe/mouse-grid-glow.ts` |

To find newer work: `gh pr list -R dreamteamapp/shapes-platform --author RotemFisch123 --state merged`.
