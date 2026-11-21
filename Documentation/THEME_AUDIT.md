# Theme & Accessibility Audit (F-17)

Date: 2026-11-21
Scope: every Qt screen, dialog, menu and custom-painted widget under the Light
and Dark Navy themes.

## Method

1. Searched the UI code for hardcoded colours (`#RGB`, `#RRGGBB`, `#RRGGBBAA`,
   `rgba(`) and for literal `white` / `#fff`.
2. Classified each hit as a theme leak or an intentional fixed colour.
3. Replaced UI leaks with `ThemeColors` fields; added missing fields to both
   themes where needed.
4. Checked WCAG AA contrast with `themes.contrast_checks()` and
   `test_theme_contrast.py` (4.5:1 text, 3:1 focus/UI boundaries).
5. Constructed the main window and the shortcut editor offscreen under each
   theme, switched theme at runtime, and checked that the palette, stylesheet
   and repaint hooks update. Visual sign-off on every dialog remains part of
   release QA because a modal blocks the in-app theme controls.

## Intentional fixed colours (not leaks)

| Area | Why fixed |
|---|---|
| Live Logs panel / log severity colours (`app.py`) | Deliberately dark in both themes; now exposed as theme-invariant `log_*` tokens (B-101) |
| `ui/smtp_help.py` HTML page | Standalone help document with its own light brand styling |
| `ui/user_manual.py` HTML page | Standalone manual with its own light brand styling |
| Google / Microsoft / Yahoo / iCloud brand badges (`ui/dialogs.py`) | Real provider brand colours |
| AIS / 26AS Excel + HTML converter colours | Output documents, not live UI |
| `_STATUS_FG` in `ui/helpers.py` | Explicit light/dark pairs chosen for both themes |
| App icon, header logos, splash artwork | Brand assets |

## Leaks fixed

| File | Change |
|---|---|
| `themes.py` | Light muted/disabled text darkened; light borders, menu border, scrollbar darkened to 3:1; light success/error/warning text darkened to 4.5:1 on their backgrounds; dark borders, menu border and scrollbar lightened to 3:1 |
| `themes.py` | Added WCAG contrast helpers and `contrast_checks()` |
| `themes.py` | Added visible `:focus` styling for buttons, checkboxes, item views and menu bar items |
| `ui/helpers.py` | Button colours now meet AA with white label text; warning uses dark label text; focus ring added; secondary button darkened |
| `app.py`, `ui/dialogs.py`, `ui/log_history.py` | `color:white` / `color:#fff` on accent backgrounds replaced with `accent_text` |
| `app.py` | `_apply_theme()` now also sets a full `QPalette`; open windows that expose `repaint_theme()` are refreshed |
| `app.py` | Saved theme (including `system`) is applied before the splash paints, removing the light flash |
| `app.py` | Removed fixed heights on text-heavy controls (search/filter/run bars, download buttons) so scaled text is not clipped |
| `app.py` | B-101: Live Logs colours moved to theme-invariant `log_*` tokens; no raw hex literals remain outside comments/HTML entities |
| `ui/dialogs.py` | B-101: only documented SMTP provider brand colours remain as literals, with a regression test guarding against unexplained hex |
| `themes.py` | B-101: added shared `log_panel`, `log_header`, `log_*` severity and button tokens |
| `resources/check_white.png` | Added a white check mark so selected checkboxes do not rely on colour alone |

## Light/Dark verification matrix

| Screen | Light | Dark | Notes |
|---|---|---|---|
| Splash → main window | OK | OK | Theme applied before splash; no light flash |
| Home / Clients | OK | OK | Table, filters, status tooltips, selection |
| Income Tax | OK | OK | Tabs and action cards use theme tokens |
| TDS | OK | OK | Tables/buttons use theme tokens |
| Mail Docs | OK | OK | Editor and preview use theme tokens |
| Activity Log | OK | OK | Intentionally dark in both themes |
| Settings | OK | OK | Theme + shortcut controls; constructed under both |
| Help | OK | OK | Help hub buttons |
| Shortcut editor | OK | OK | Constructed and validated under both themes |
| Other dialogs | Code-reviewed | Code-reviewed | Constructed with the active theme; live repaint where supported |

## Live repaint

`_apply_theme()` updates the app stylesheet/palette and calls
`_repaint_open_windows()`, which re-themes any open window that exposes a
`repaint_theme(t)` method (`NavShell`/`NavRail` today). Modal dialogs capture the
theme when constructed; because a modal blocks the main window's theme controls,
they are always created with the current theme. A global shortcut cannot fire
while a modal is open.

## Remaining watch items

- Third-party/provider dialogs (native file pickers) follow the OS theme.
- The Live Logs panel stays dark by design; it is not a dark-mode leak.
