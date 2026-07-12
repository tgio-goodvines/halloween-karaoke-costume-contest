# UI/UX Design System

## Current Visual Direction

The app now uses a dark lab-terminal Halloween style based on the provided UI kit. Treat this as the canonical direction for all attendee, admin, bartender, RSVP, live-display pages, and generated HTML emails.

Core traits:

- Background: near-black `#161516` with subtle red atmospheric glow and CRT scanline overlays.
- Typography: `Libre Baskerville` for display/page headings and `IBM Plex Mono` for body text, controls, metadata, and status text.
- Palette: primary blood red `#ff3131`, dark blood `#9b1235`, hot red `#ff2d55`, steel `#3d3f43`, magenta `#b16d96`, and dusty rose `#ebaeb6`.
- Surfaces: square-edged lab/classified panels with red borders, inset glow, subtle scanline texture, and no soft rounded-card look.
- Controls: square mono uppercase buttons, red primary actions, transparent/outlined secondary actions, visible focus glow, and touch-safe sizing.
- Inputs: dark scanline fields with red borders, dusty-rose text, and red focus rings.
- Status language: small uppercase badge treatments for RSVP/update/menu/order/status labels, plus small red LED pips for decorative system/live states.
- Motion: CRT scanline overlays remain subtle; the vertical scan bar should stay slow enough to feel atmospheric instead of distracting.
- Live display: same lab-system language at larger scale, with serif glowing headings, square display cards, scoreboard panels, LED-style metric accents, and high-contrast override cards.
- HTML email: same palette and square lab-panel language, implemented with email-safe inline CSS, table wrappers, dark backgrounds, red borders, dusty-rose links, uppercase mono-style buttons, and Georgia/Courier fallbacks rather than relying on external web fonts. Email templates should use `#ff3131` for primary borders/buttons/badges.

## Implementation Notes

- `static/styles.css` owns the shared app UI for RSVP, login/register, party dashboard, menu, bartender, admin, costume signup, karaoke signup, and voting.
- `static/display.css` owns the TV/live-display visual system and should stay visually aligned with `static/styles.css`.
- `templates/email/*.html` own generated HTML email styling and should stay visually aligned with the same design system using inline, email-client-friendly CSS.
- `templates/base.html` includes the header wordmark plus clearance/live status indicators; keep those status elements decorative and do not turn them into separate navigation or logout controls.
- Existing Jinja template structure is intentionally preserved. Prefer extending shared classes and CSS variables over broad template rewrites.
- Keep `/rsvp` as a standalone public page without the header nav menu.
- Keep the single logout action inside the `Menu` disclosure.
- Use square corners for panels/buttons/inputs unless a specific control requires a different shape for usability.
- Avoid reverting to the older red-on-black rounded Halloween style.
- Do not add Tailwind, FontAwesome, or other external runtime UI dependencies from reference kits; translate kit ideas into the existing static CSS and inline-email structure.
