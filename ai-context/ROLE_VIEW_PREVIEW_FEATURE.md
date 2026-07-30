# Admin Role View Preview

## Implemented 2026-07-30

Admins can open **Admin → Public Info → Role View Demo** and select Attendee,
Bartender, or Admin. The selected preview is stored only in that browser's
Flask session under `role_preview`; it is not Redis state and does not affect
any account, other browser, or production party data.

The preview uses the normalized real-world role sets: Attendee is `regular`,
Bartender is `regular` plus `bartender`, and Admin is `admin`. The shared
navigation retains links that the browser can access through additional real
session roles, but marks and disables them as **Hidden**. This makes it clear
which controls a person in the previewed role would not see, while keeping the
admin's recovery path visible in the role-preview banner.

## Safety Boundary

- `session_roles()` remains the only authorization source for route guards and
  mutations.
- `preview_roles()` is presentation-only and must never be used for access
  checks or state changes.
- Role preview cannot grant a permission. A link retained by a real additional
  session role is non-interactive while marked Hidden.
- The banner's **Exit Preview** action posts to the existing admin portal and
  clears only the local session key.

## Verification

Regression coverage confirms an admin/regular/bartender combined session can
preview Attendee, sees Bartender and Admin navigation marked Hidden, retains
its actual server authorization, and restores the normal view after exit.
