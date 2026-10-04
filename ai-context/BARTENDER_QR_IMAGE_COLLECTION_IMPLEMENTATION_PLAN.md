# Bartender QR Image Collection Implementation Plan

## Implementation Status

Implemented locally on 2026-10-04. Schema 25, Redis-backed QR media, legacy singleton
migration, one independently named QR entry per supported payment method,
admin CRUD/reordering, attendee QR cards, provider-specific dashboard slides,
robust Pillow validation, legacy release-file preservation, and regression
coverage are complete. The existing admin FormData transport was retained; no
QR-specific JavaScript controller was necessary. Production deployment and its
multi-instance smoke test remain external rollout steps.

## Goal

Extend the existing bartender tipping feature from one shared QR/payment image
to locally uploadable QR images for Zelle, PayPal, Venmo, and Cash App. Each
payment method may have one QR entry with its own stable identity and
independently editable display name.

This is a focused extension of the existing tip feature. It does not change
bartender account permissions, drink ordering, the protected bartender queue,
payment processing, generated QR codes, live-display bar operations, or email.

## Pre-Implementation Assessment

The app already supports one local bartender-tip upload:

- `templates/admin.html` submits `tip_image_upload` as multipart form data.
- `main.py::save_uploaded_bartender_tip_image()` accepts PNG, JPG, GIF, and
  WebP files up to 5 MiB and writes them beneath
  `static/uploads/bartender-tips`.
- `bartender_tip_settings` persists only one overall `display_name`, one
  `image_url`, one note, and the four optional payment handles.
- `templates/bartender_tip.html` renders one image.
- `main.py::party_dashboard()` creates one tipping slide with that image.
- `_personal_drink_orders.html` correctly renders only one callout linking to
  the dedicated tipping page.

The current upload path is unsafe across production releases. The default
upload directory is inside the checked-out release, while
`deploy/ec2_deploy_from_github.sh` creates a fresh
`/opt/halloween/releases/<sha>` from `git archive` and repoints
`/opt/halloween/current`. It neither copies prior uploads nor provides shared
filesystem storage. `HALLOWEEN_BARTENDER_TIP_UPLOAD_DIR` alone does not solve
this because saved URLs still use Flask's `/static/...` route.

The app already has the correct multi-instance pattern for menu images:
validated bytes are stored under separate Redis binary keys and served from an
immutable application route. Bartender QR assets should reuse that approach
with a separate namespace.

## Confirmed Scope

### In scope

- Add, name, edit, enable/disable, reorder, replace, and remove one individual
  QR entry per supported payment method.
- Upload one local image per add/replace action.
- Continue to allow an optional supported image URL for an entry.
- Require every new or edited QR entry to select Zelle, PayPal, Venmo, or Cash
  App, and prevent two entries from selecting the same method.
- Preserve the overall tip heading/display name, note, and existing global
  payment-handle text fields, pairing each handle only with its method's QR.
- Show enabled named entries consistently in admin, on the attendee tipping
  page, and in party-day dashboard highlights.
- Store new uploaded bytes in Redis so every API instance and release can
  serve them.
- Migrate the existing singleton setting without data loss.

### Out of scope

- Generating or validating the destination encoded by a QR code.
- Taking payments or linking payment-provider accounts.
- Assigning QR entries to bartender-role accounts.
- Adding tip QR codes to `/bartender`, drink-ready notices, the TV live
  display, APIs, or email.
- Reworking the attendee Menu & Orders boundary.

## Proposed State Contract

Bump `STATE_SCHEMA_VERSION` from 24 to 25 and extend the existing setting:

```json
{
  "enabled": true,
  "display_name": "Your Bartenders",
  "note": "Tips are never required, always appreciated.",
  "qr_codes": [
    {
      "id": "stable-32-character-id",
      "name": "Casey",
      "payment_method": "venmo",
      "image_url": "/bartender-tip-images/asset-id.png",
      "enabled": true,
      "created_at": "2026-10-04T18:00:00Z",
      "updated_at": "2026-10-04T18:00:00Z"
    }
  ],
  "zelle": "",
  "paypal": "",
  "venmo": "",
  "cash_app": ""
}
```

Rules:

- Entry identity is `id`, never the name, filename, or list index.
- List order is display order.
- `name` is required, trimmed, and limited to 80 characters.
- `payment_method` is required for new and edited entries, is restricted to
  `zelle`, `paypal`, `venmo`, or `cash_app`, and must be unique in the list.
- `image_url` must be a supported external/static URL or the exact managed QR
  route. Add requires an image; edit may retain the existing image.
- `updated_at` is the stale-form revision, following the current menu-item
  pattern.
- Limit the collection to four entries, one per supported payment method.
- An empty `qr_codes` list in schema 25 is authoritative. Deleting the last
  entry must not resurrect the legacy singleton image.

Keep legacy `image_url` readable only during migration/compatibility. New UI
and presentation helpers must use `qr_codes`. Do not use a fallback from an
empty schema-25 collection to `image_url`.

## Migration Design

Add a schema-25 migration before normal state application:

1. Write one raw 30-day backup at
   `halloween:state:backup:schema25-bartender-tip-qr`.
2. When a pre-25 setting has a non-empty `image_url`, create exactly one QR
   entry using the old `display_name` as its label and preserve the URL. Assign
   its payment method when exactly one payment handle is configured; otherwise
   leave the migrated entry explicitly unassigned for an admin to select.
3. When the old image is empty, create an explicit empty collection.
4. Preserve overall enablement, note, and all payment handles.
5. Make the migration idempotent and persist schema 25 after a successful
   load.

State migration is not enough for a legacy URL under
`/static/uploads/bartender-tips/`. Before switching releases, inspect the live
state:

- Preserve external URLs and tracked `/static/` assets as URLs.
- For a generated local upload, read the file from the previous release while
  it still exists, validate it, store it in the new Redis asset namespace, and
  rewrite the migrated entry to the managed URL.
- If the referenced file is missing, retain an explicit admin warning and
  require replacement. Do not mark the asset as successfully migrated.

Because production can contain more than one API instance and deploys them
sequentially, use an expand/activate rollout:

1. Deploy compatibility code that preserves `qr_codes` during normalization
   but does not yet expose write actions.
2. Confirm every instance runs that compatible version.
3. Deploy/activate the collection UI and schema-25 writer.

This prevents an older instance from loading and saving the state while
silently dropping the new collection.

## Managed Asset Storage

Add a dedicated namespace and route rather than writing into a release:

- Redis key: `halloween:bartender-tip-image:<asset-id>:<extension>`
- URL: `/bartender-tip-images/<asset-id>.<extension>`
- Supported formats: PNG, JPG/JPEG, GIF, and WebP.
- Compressed size: maximum 5 MiB per request/image.
- Response: exact image MIME type plus
  `Cache-Control: public, max-age=31536000, immutable`.
- New asset IDs on replacement prevent stale browser caches while the QR entry
  ID remains stable.

Refactor the menu and bartender upload code around shared prepare/validate
helpers while retaining separate storage namespaces and error messages.

Validation should include:

- sanitized filename and allowlisted extension;
- allowlisted MIME/format agreement;
- bounded read before storage;
- magic signature validation;
- full decoder verification and a decoded-pixel/dimension ceiling.

Full decoder verification requires adding Pillow to `requirements.txt`. Apply
the same validator to menu images so the two admin upload paths do not have
different safety guarantees. Replace the current fake-signature test payloads
with genuine minimal image fixtures.

### Commit and cleanup behavior

An asset must not become a permanent orphan when metadata validation or state
persistence fails:

1. Authenticate and validate CSRF through the existing request hooks.
2. Validate the entry name, revision, URL, and all other metadata first.
3. Prepare and validate image bytes without publishing them.
4. Store a candidate asset with a short TTL.
5. Persist the state reference and make the candidate permanent in one
   lock-protected Redis transaction.
6. On replacement/removal, retain the old managed asset with a 30-day TTL so
   state recovery backups remain usable, then allow it to expire.

Development memory fallback may keep bytes in a dedicated dictionary, but
production must fail clearly if Redis binary storage is unavailable.

Before rollout, verify that Redis persistence, backups, capacity, and eviction
policy cover the new binary key namespace. State JSON backups do not themselves
contain image bytes.

## Backend Changes

### `main.py`

- Bump the schema to 25 and add the raw backup/migration function.
- Add `qr_codes` to `DEFAULT_BARTENDER_TIP_SETTINGS`.
- Add pure QR-entry and collection normalizers.
- Update `normalize_bartender_tip_settings()` to preserve the collection.
- Add helpers to find one entry by stable ID and reject missing/duplicate IDs.
- Add a presentation helper returning enabled, valid entries in saved order.
- Extend `safe_image_url()` for only the exact managed QR URL format.
- Replace `save_uploaded_bartender_tip_image()` with prepare/store/commit
  helpers backed by Redis binary keys.
- Add `GET /bartender-tip-images/<image_id>.<extension>` using the same
  validation and cache behavior as `/menu-images/...`.
- Change `bartender_tip_settings_from_form()` so it updates only the overall
  settings and merges rather than replaces `qr_codes`.
- Add admin actions:
  - `add_bartender_tip_qr`
  - `update_bartender_tip_qr`
  - `delete_bartender_tip_qr`
  - `move_bartender_tip_qr` with an explicit direction
- Require the submitted `updated_at` value on entry updates/deletes and reject
  stale forms.
- Keep all mutations inside the existing admin authorization, CSRF, and Redis
  state-lock lifecycle.
- Update `party_dashboard()` to build one named tipping slide per enabled QR
  entry. If no enabled QR exists but handles are configured, retain one
  text-only tipping slide.
- Pass the normalized presentation collection to admin and attendee templates.

No change is needed to the bartender queue context, drink-order model,
attendee-safe bar API, or display payload.

## Template and CSS Changes

### `templates/admin.html`

Keep the overall enable/display-name/note/payment-handle form, but remove its
singleton image inputs. Add a compact QR collection beneath it:

- one collapsed **Add QR Code** multipart form;
- one collapsed editor per entry with preview, name, enabled state, optional
  replacement upload/URL, revision, move controls, and confirmed remove;
- a clear empty state and migration/storage warning area;
- stable `data-view-key` values based on entry ID so in-place admin updates
  restore the correct disclosure and viewport.

A small `_admin_bartender_tip_qr.html` partial is recommended to prevent the
already-large admin template from growing further.

The existing `static/preserve-scroll.js` already submits `FormData` and
reinitializes the replaced panel through `admin:panel-updated`; no transport
rewrite is required. A new JavaScript controller is optional, not required for
the first implementation. Server-rendered forms must work without JavaScript.
On validation errors, repopulate typed text/checkbox values from a server-side
draft. Browsers cannot safely restore a selected local file after a response,
so the error must explicitly ask the admin to reselect it.

### `templates/bartender_tip.html`

- Render a responsive grid/list of enabled QR cards.
- Put each entry's visible name immediately beside its matching QR image.
- Preserve source aspect ratio and sufficient quiet space; do not overlay
  decorative effects on the QR itself.
- Keep the overall note and global payment handles outside the cards.
- Provide an actionable empty state when tipping is enabled but no usable QR
  exists.

### `templates/index.html`

- Support an optional dashboard-slide CTA to `/party/bartender-tip`.
- Render the name supplied by each QR-specific slide.
- Preserve current text-only tipping behavior when only handles are configured.

### `templates/_personal_drink_orders.html`

Keep one tipping callout linking to the dedicated page. Do not duplicate every
QR image in each order/history section.

### `templates/drink_history.html`

No functional change is required. The route is a compatibility redirect to
the consolidated Menu & Orders workspace. Remove or update its dormant tip
markup only if that retired template is intentionally cleaned up.

### `static/styles.css`

Add responsive QR collection/admin preview classes within the current modern
dark-neon system. Use bounded `object-fit: contain`, high contrast, readable
labels, touch-safe controls, and mobile single-column fallback. QR pixels and
quiet zones must remain unobscured and scannable.

## Test Plan

Extend `tests/test_redis_state.py` with:

- schema-24 singleton-to-schema-25 collection migration;
- no-image migration to an explicit empty collection;
- migration idempotency and raw backup retention;
- deleting the final entry without legacy resurrection;
- snapshot/apply/load round trips for IDs, names, order, enabled state, and
  revisions;
- two uploads with the same client filename but distinct names and asset URLs;
- rename without replacement and replacement without rename;
- independent disable, reorder, and delete behavior;
- stale/missing/duplicate entry ID rejection;
- overall-settings save preserving the collection;
- supported external URL preservation;
- managed image route bytes, MIME, immutable caching, invalid ID/extension,
  missing asset, and Redis failure responses;
- rejection of empty, oversized, unsupported, spoofed, truncated,
  excessive-dimension, and decoder-invalid files;
- failed metadata/storage/state commits leaving the prior entry intact and no
  permanent candidate asset;
- admin/CSRF authorization coverage outside testing mode;
- consistent name/image/order rendering in admin, `/party`, and
  `/party/bartender-tip`;
- My Orders retaining one callout only;
- disabled/empty/broken-image states.

Add browser/manual verification for:

- add/edit/replace/reorder/delete with JavaScript enabled and disabled;
- in-place admin panel replacement, open disclosure, focus, and scroll
  restoration;
- phone and desktop layouts;
- real phone scanning of every supported file format actually retained;
- same image retrieval from every API instance;
- image retrieval after a production release switch.

Run the full Python and Node suites, compile `main.py`, and retain the existing
deployment-script validation in GitHub Actions.

## Implementation Sequence

1. **Compatibility and model:** add schema-25 types/normalizers, legacy
   preservation, backup, presentation helper, and migration tests without
   enabling collection writes.
2. **Shared media:** add the Redis namespace/route, common robust validator,
   atomic candidate lifecycle, and storage tests.
3. **Admin CRUD:** split overall settings from per-entry actions and implement
   stable-ID/revision-safe add, update, replace, enable, move, and remove.
4. **Attendee rendering:** update the dedicated tip page and dashboard slides;
   keep the single My Orders callout.
5. **Legacy asset import:** migrate any release-local production file while the
   prior release remains available and surface missing-file warnings.
6. **Verification and rollout:** run automated/responsive/scanning tests,
   verify Redis operations, deploy compatibly across all instances, and smoke
   test the managed image URL after the release switch.

## Acceptance Criteria

- An admin can upload two local files with the same filename, give them
  different names, and see the correct name/image pair everywhere.
- Renaming one entry does not replace its image or modify another entry.
- Replacing one image does not change its entry name or stable ID.
- Disabling, moving, or deleting one entry does not affect the others.
- Overall note/handle edits never erase QR entries.
- Enabled QR entries retain their order and remain available across app
  restarts, EC2 instances, and deployments.
- Legacy singleton settings migrate once without duplicate or resurrected
  entries.
- Invalid or failed uploads leave existing state/assets usable and do not
  create permanent orphaned data.
- Attendees see only the intended named QR collection and can scan the images
  on phone and desktop layouts.
- Bartender queue authorization and operational behavior remain unchanged.

## Assessment of the Referenced ChatGPT Proposal

The referenced ChatGPT assessment reviewed the same local HEAD commit,
`a1b8089d280fc3b43f28807bf087d7b80ff86f29`, and its central conclusions are
valid for this app:

- current support is singleton, not independently named/multiple;
- default upload storage is release-local and can break after deployment;
- Redis-backed menu-image storage is the correct internal precedent;
- the normalizer, admin action, dedicated tip page, dashboard slides, and tests
  all require coordinated changes;
- the bartender queue, live TV display, and emails do not need changes.

The proposal's new JavaScript controller, ten-entry limit, per-entry revision,
and Pillow-based decoder checks are design recommendations rather than facts
already required by the app. This plan adopts the limit/revision and robust
decoder checks, but keeps JavaScript optional because the existing FormData
admin transport is already sufficient. Its warning about preserving an
uploaded file input after a validation response also needs qualification:
typed fields can be restored, but the browser must require the local file to be
selected again.
