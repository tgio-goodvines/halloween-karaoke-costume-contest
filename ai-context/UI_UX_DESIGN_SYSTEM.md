# UI/UX Design System

## Current Visual Direction

The app now follows the attached modern dark neon wireframe kit. Treat this as
the canonical direction for attendee, admin, bartender, RSVP, live-display
pages, and generated HTML emails.

Core traits:

- Background: deep void `#0d0d0d` with soft red atmospheric radial glows.
- Typography: `Outfit` for headings, labels, badges, and commands; `Figtree`
  for body text. Existing IBM/Libre imports may remain as fallbacks only.
- Palette: neon red `#ff3131`, neon dark `#c42020`, neon soft `#ff5555`,
  surface `#1a1a1a`, raised surface `#222222`, zinc light `#f4f4f5`, zinc mid
  `#a1a1aa`, zinc dim `#52525b`, and zinc borders `#27272a`/`#3f3f46`.
- Surfaces: rounded glass/backlit panels with subtle white borders, red top
  edge glow, backdrop blur, and deep black shadow. Avoid returning to the
  square classified-terminal look.
- Controls: rounded halo buttons, gradient red primary actions, red-tinted
  secondary actions, ghost buttons with soft white borders, visible focus glow,
  and touch-safe sizing.
- Inputs: rounded dark translucent fields with subtle white borders, red focus
  halo, and zinc placeholder text.
- Status language: pill badges with dots for live/critical/online states.
- Header status: avoid standalone/orphaned LED dots. Decorative LED pips should sit beside meaningful text or be removed.
- Motion: glow and hover motion should be subtle; avoid distracting scan bars.
- Live display: same modern dark neon language at larger scale, with Outfit
  headings, rounded backlit display cards, pill classification labels, and
  high-contrast but not fully square override cards.
- HTML email: same palette and dark panel language, implemented with email-safe
  inline CSS, table wrappers, dark backgrounds, red borders, zinc/dusty links,
  uppercase buttons, and Georgia/Courier fallbacks rather than relying on
  external web fonts. Email templates should use `#ff3131` for primary
  borders/buttons/badges.

## Implementation Notes

- `static/styles.css` owns the shared app UI for RSVP, login/register, party dashboard, menu, bartender, admin, costume signup, karaoke signup, and voting.
- `static/display.css` owns the TV/live-display visual system and should stay visually aligned with `static/styles.css`.
- `templates/email/*.html` own generated HTML email styling and should stay visually aligned with the same design system using inline, email-client-friendly CSS.
- `templates/base.html` includes the header wordmark plus clearance/live status indicators; keep those status elements decorative and do not turn them into separate navigation or logout controls.
- Existing Jinja template structure is intentionally preserved. Prefer extending shared classes and CSS variables over broad template rewrites.
- Keep `/rsvp` as a standalone public page without the header nav menu.
- Keep the single logout action inside the `Menu` disclosure.
- Use rounded modern kit corners for panels/buttons/inputs; do not reintroduce
  the square terminal panel treatment.
- Avoid reverting to the older red-on-black Halloween style.
- Do not add Tailwind, FontAwesome, or other external runtime UI dependencies from reference kits; translate kit ideas into the existing static CSS and inline-email structure.

## 2026 Wireframe Refinement Notes

- The attached modern dark neon wireframe kit has been translated into final
  override layers at the end of `static/styles.css` and `static/display.css`.
- Keep future refinements in the same spirit: void background depth, red
  atmospheric glow, rounded backlit cards, pill badges, halo buttons, and
  Figtree/Outfit typography.
- The wireframe's Tailwind and FontAwesome implementation details were not
  adopted; the repo remains dependency-free for UI styling.
- Generated email styling is centralized through `templates/email/_components.html`.
  Continue using inline styles, table wrappers, Georgia/Courier fallbacks, and
  `#ff3131` primary borders/buttons.
