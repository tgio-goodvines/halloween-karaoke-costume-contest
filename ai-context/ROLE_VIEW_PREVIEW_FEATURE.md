# Admin Role View Preview

## Implemented 2026-07-30

Admins can open **Admin → Public Info → Role View Demo** and select Attendee,
Bartender, or Admin. The selected preview is stored only in that browser's
Flask session under `role_preview`; it is not Redis state and does not affect
any account, other browser, or production party data.

The preview uses the normalized real-world role sets: Attendee is `regular`,
Bartender is `regular` plus `bartender`, and Admin is `admin`. The shared
navigation retains links supplied by additional real session roles, but marks
and disables them as **Hidden**. Protected routes also use the selected preview
roles, so an Attendee preview cannot open the bartender or admin views.
The bartender marker is capability-based: both a bartender assignment and an
admin override can grant that view, so it is marked Hidden whenever neither is
part of the selected preview.

## Safety Boundary

- `session_roles()` remains the source of real permissions; `preview_roles()`
  can only reduce the effective roles while the demo is active, never grant one.
- Protected routes use preview roles so the selected role cannot open a view it
  would not normally have. State mutations still require that route access.
- Role preview cannot grant a permission. A link retained by a real additional
  session role is non-interactive while marked Hidden.
- The banner's **Exit Preview** action uses a dedicated real-admin-verified
  endpoint, so the host can recover even when an Attendee preview hides admin.

## Verification

Regression coverage confirms an admin/regular/bartender combined session can
preview Attendee, sees Bartender and Admin navigation marked Hidden, cannot
open those protected views, and restores the normal view after exit.
