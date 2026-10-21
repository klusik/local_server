# Desktop design guidance

Read this file before changing anything inside `src/local_server/ui`.

## Visual direction

Use PHP Gallery's `winapp/uploader/ui_theme.py` as the visual reference:
dark slate surfaces, cyan accents, pale text and quiet layered panels.
Local Server owns its implementation; do not import from the other checkout.

- Centralize colors and reusable controls in `ui/theme.py`.
- Prefer whitespace, alignment and surface changes to outlines and group boxes.
- Use compact icon actions for familiar secondary operations. Always attach a
  tooltip available on hover and keyboard focus. Keep a short label on primary
  actions and on ambiguous or consequential controls.
- Use pill switches for boolean settings, never classic square checkboxes.
  Support Tab focus and Space/Return activation, with a visible focus indicator.
- Keep explanatory text brief. Put detail in contextual help rather than
  repeating implementation notes throughout the workspace.
- Use a single cyan primary action and restrained hover/pressed states.
- Keep the slate palette soft: nearby surface tones, muted cyan and off-white
  text. Avoid bright outlines and high-contrast panel edges.
- Use subtle six-pixel rounded corners on fields, buttons, tabs and cards.
  Shared nine-slice artwork provides rounding without external dependencies.
- Tab labels must retain identical padding, font, insets and dimensions in all
  states. Selection changes only the surface tint and text tone, never size.
- Keep body text opaque and readable. Suggest glass through layered slate
  colors; do not lower whole-window opacity, including text and controls.
- Actual backdrop blur/transparency is optional platform enhancement work;
  retain an opaque fallback and native window resizing and title-bar behavior.
- Use native file pickers and system message dialogs where appropriate.
- Preserve keyboard navigation, scaling, contrast, and honest runtime states.
- No external UI dependencies or image downloads without a concrete need.

## Current implementation

The shared ttk theme styles the workspace, tables, fields, tabs and actions.
`ToggleSwitch` supplies the MySQL pill control; `icon_button` supplies tooltip
help. No native blur or OS compositor integration is currently implemented.
Windows and macOS keep the same palette with platform font selection.
