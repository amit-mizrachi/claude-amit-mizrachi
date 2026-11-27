---
name: rotem-design
description: Design Shapes UI the way Rotem (Shapes' designer-engineer) ships it. Use when designing, redesigning, restyling or polishing a screen, dialog, card, list or menu in shapes-platform's io-client, or when reviewing a UI diff for whether it looks native to Shapes.
---

# rotem-design

Rotem's surfaces read as one calm app: the same card, row, dialog and status control everywhere, Shapes UI tokens, one accent, short copy, and numbers measured on the real screen. This skill turns Rotem's merged shapes-platform PRs into rules. Paths are relative to `apps/dreamteam-io-client/src/` unless they say otherwise; `CD/` = `components/connections-view/connectors-directory/`.

The token values (spacing, radius, type, colour, motion, icons, copy) live in [`references/patterns.md`](references/patterns.md). Read it before Step 3. The source files of every pattern, and the `@shapesos/ui` imports, live in [`references/components.md`](references/components.md). Read it in Step 2.

## Step 1 - Find the closest Rotem surface

For each surface you will touch, name the shipped Rotem surface it should look like, then read that surface's styles file. Start from this table:

| You are building | Copy this surface | Styles file |
|---|---|---|
| A catalog of many things | Connectors directory cards (88px, 2-col grid) | `components/settings-catalog-card/settings-catalog-card-styles.ts` |
| A settings page | Account Settings header row + 1000px column | `styled-mixins/settings-column-mixin.js`, `styled-mixins/settings-page-title-mixin.js`, `CD/connectors-directory-component-styles.ts` |
| A detail page for one thing | Connector page (logo tile, title, status, one action, 2-col sections) | `CD/connector-page/connector-page-component-styles.ts` |
| A consent, connect or add step | Connect step (`AlertDialog` drawn as the app's modal) | `CD/connect-consent/connect-consent-dialog-component-styles.ts` |
| A destructive confirm | Disable connector dialog | `CD/disable-confirm/disable-connector-dialog-component.tsx` |
| A row list with on/off per item | Chat Connectors panel rows (44px, 28px tile, `Switch`) | `connections-view/mcp-connections-menu/connectors-panel-component-styles.js` |
| A few things to act on inside a dialog | Vibe connect popup framed rows | `features/vibe/vibe-connect-popup/vibe-connect-popup-component-styles.ts` |
| A status that is also a control | Connector status square (outline "+", green-tinted check) | `CD/connector-trust/connector-trust-components-styles.ts` |
| A hover hint | `HintComponent` | `components/settings-catalog-card/hint-component.tsx` |
| A release or announcement popup | Shapes AI release popup (reuses Performance Reviews layout) | `components/shapes-ai-release/shapes-ai-release-component-styles.ts` |

Done when every surface has one named source file that you have read. When nothing fits, pick the nearest row and write in a comment which surface you adapted and why.

## Step 2 - Map each surface

Write a short map before you edit, one line per surface: the file that renders it now, the Rotem source from Step 1, and the concrete deltas (each one a token, a component or a copy key). Example line:

    Product picker | CD/connect-consent/connect-consent-dialog-component.tsx | copy connectors-panel Row | Checkbox -> Switch size="sm"; 16px bare logo -> 28px tile radius 8; plain list -> framed list radius 10

Done when every delta names a token, a component or a file. A delta like "make it cleaner" is not a delta.

## Step 3 - Build

Apply the rules below and the values in `references/patterns.md`.

1. **Reuse the pattern and cite it.** Copy the source surface's structure and put its file in a one-line comment (`// Row anatomy from connectors-panel-component-styles.js (Rotem, connectors)`). Share one styled block when two surfaces need the same row, so they cannot drift.
2. **Build on `@shapesos/ui`.** Import `Button`, `Switch`, `AlertDialog`, `DropdownMenu`, `Card`, `InputGroup`, `Tooltip` from `@shapesos/ui/<name>` and restyle with a styled-components wrapper using `&&` for specificity. Local styled divs are right for row anatomy, because that is what Rotem's rows are.
3. **Colour with Shapes UI variables.** `var(--foreground)`, `var(--muted-foreground)`, `var(--muted)`, `var(--border)`, `var(--background)`, `var(--success)`, `var(--ring)`. Raw `rgba()` belongs only in shadows, backdrops and the agent glow. One accent per surface.
4. **Keep geometry even.** Fixed heights for cards and rows, one-line names and descriptions with ellipsis, concentric radii (inner = outer - padding), the 4-based spacing scale. Write the arithmetic behind any non-scale number in a comment (`/* 12 gap + 32 tile + 12 pad */`).
5. **Make the primary button the consent.** It names verb + object ("Connect {name}", "Add {name}"). The dialog explains what is read as an icon list, then one muted note on whose access it uses.
6. **Draw dialogs as the app's modal.** Plain 50% black backdrop, no blur, scoped with a `createGlobalStyle` `:has(~ [data-<name>])` rule; width 480-520; padding 24; footer with a full-width top rule and buttons on the right (outline secondary, then primary); a consent or connect dialog puts initial focus on the primary action, but a destructive confirm leaves focus on the cancel ("Keep {name}") and never focuses the destructive action.
7. **Status on the right, as a control.** Not connected: outline icon square with `IconPlus`. Connected: the same square or a "Connected" pill tinted with `color-mix(in srgb, var(--success) 22%/9%/15%, var(--background))`, opening a `DropdownMenu` whose `DropdownMenuItem variant="destructive"` is the remove action.
8. **Per-item on/off is a `Switch` in a row.** The whole row is a `<label>` with `cursor: pointer` and a `var(--muted)` hover. Several items to choose from in a dialog sit in one framed list (1px `var(--border)`, radius 10).
9. **Give every icon-only control a hint and a name.** `HintComponent` with state + action ("{name} is connected. Click to disconnect") and an `aria-label`. `:focus-visible` = 2px `var(--ring)` outline, offset 2.
10. **Write the copy in Rotem's voice.** Sentence case, short, buttons verb + object, states one word ("Connected"), dialog titles a short question naming the thing ("Connect {name}?"), toasts without "successfully" and without a full stop. Author only `translations/en.json`; the i18n bot fills the other locales. Run `agent-skills:shapes-copy-guidelines` on new strings when it is available.
11. **Size layouts to content.** `flex-wrap`, `clamp()`, "drop under when no room". Translated labels are longer than English, so a breakpoint tuned to English breaks in German.
12. **Keep one look everywhere a surface opens.** When a variant becomes dead, delete its styles in the same PR.
13. **Gate new UI behind the feature's flag.** A test proves the flag-off path renders as on main.

## Step 4 - Prove it

Rotem proves UI with the screen, not with a claim.

- Take a before and an after screenshot of every surface you changed, at the same window size and with the same data. Publish them as a "Before | After" table (in the PR body or a claude.ai artifact), each image with full alt text.
- Measure the decisions that carry numbers on the running page with `getBoundingClientRect` and computed styles (heights, gaps, radii, colours), and put the values in the PR body.
- Write the PR body in Rotem's order: What -> Why -> How -> Who sees it (flags) -> Evidence (measured) -> Not verified -> Merge Danger (Door, Blast Radius) -> How to test (numbered, with flags).

Done when every changed surface has a before/after pair and the "Not verified" list names everything you did not see on a screen.

## Review checklist

Run it on your own diff before you call the work done, and on any UI diff you review.

- [ ] Each changed surface cites its Rotem source file in a comment.
- [ ] Controls come from `@shapesos/ui`; restyles use `&&` wrappers.
- [ ] Colours are Shapes UI variables; raw `rgba()` appears only in a shadow, backdrop or glow; one accent per surface.
- [ ] Spacing is on the 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64 scale, or its arithmetic is in a comment.
- [ ] Radii are concentric; logo tile radius matches its size (28->8, 32->8, 44->10, 64->16).
- [ ] Cards and rows have fixed heights; long names end in an ellipsis on one line.
- [ ] Icons are Tabler, 16px muted in text rows, 20px in buttons; brand logos sit in a bordered tile.
- [ ] Dialogs: plain 50% backdrop, padding 24, footer rule, buttons right, primary names the action, consent dialogs focus the primary, destructive confirms focus the cancel.
- [ ] Every icon-only control has a hint and an `aria-label`; focus ring is `var(--ring)`.
- [ ] Copy: sentence case, verb + object buttons, one-word states, no "successfully"; a state that is not an error uses neutral text.
- [ ] Empty, loading, error and disabled states exist and match `references/patterns.md` States.
- [ ] Motion is 100-700ms, eased, never restarted mid-play, with a `prefers-reduced-motion: reduce` branch; heights stay fixed while content changes.
- [ ] Nothing sits within 56px (`os.window.CLOSE_BUTTON_CLEARANCE`) of the window X or covers another control.
- [ ] New UI is behind its flag; a test covers the flag-off path.
- [ ] Before/after screenshots and measured numbers are in the PR, with a "Not verified" list.
