# Attendee Account Management Feature

## Status

Implemented on 2026-07-30. The attendee account workspace lives at
`/party/account` and is linked as **Account** in the shared `Menu` disclosure
for signed-in regular attendees. It remains available before the party day.

## Account Workspace

- Requires the `regular` session role; unauthenticated visitors are sent to
  `/party/login` with a safe return path.
- Shows the display name, email, account creation date, account level, stored
  account roles, and the current browser session permissions.
- The separate stored-role and session-permission values intentionally aid
  hosts debugging a role change that has not yet been reflected in a browser
  session.
- Lets the attendee change their display name and email. The stable account ID
  is preserved, so existing drink orders, voting, and other ID-keyed records
  remain associated with the person. The active session/header name updates
  immediately.
- Lets the attendee change their password after verifying the current password.
  Passwords remain stored only as Werkzeug hashes.
- Profile identity changes and password changes invalidate outstanding password
  reset tokens for the account. The email-based forgotten-password flow remains
  available.

## Access Boundaries

- Attendees cannot change roles, delete accounts, or access other accounts.
- Role assignment/removal and account deletion remain admin-only operations in
  `/admin/accounts`.
- Every account-page form uses the app's existing CSRF protection and Redis
  mutation lock/persistence lifecycle.

## Verification

`tests/test_redis_state.py` covers sign-in protection, menu navigation, role
and session-permission rendering, profile update persistence, stable-ID
preservation, profile validation, password verification/update, reset-token
invalidation, and login with the new password.
