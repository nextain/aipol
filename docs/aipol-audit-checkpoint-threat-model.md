# AIPOL external audit checkpoint threat model

## Security claim

SQLite is not its own trust anchor. After every committed audit event, the event-tool creates a keyed checkpoint in
a separately scoped store. Readiness and administrative mutations compare the complete remote sequence with the
local chain and require the same database instance ID and exact final head. Production startup fails when this
external checkpoint cannot be verified.

Each checkpoint contains only `version`, `sequence`, `head_hash`, `previous_hash`, `db_instance_id`,
`schema_version`, `created_at`, `key_id`, and an HMAC-SHA-256 `signature`. Its blob name is derived from the
20-digit sequence and creation uses `If-None-Match: *`; overwrite is never an application operation.

## Trust boundaries

- SQLite/Azure Files contains detailed events and is assumed writable by the application process.
- The dedicated Blob container uses versioning and a locked time-based immutability policy. The app identity has a
  custom container-scoped role with blob read/write only: no delete, permanent-delete, version-delete, Blob Data
  Contributor, or immutability-policy superuser action.
- The versioned HMAC keyset is a named-secret Key Vault reference. The active ID selects only new checkpoints; old
  key IDs remain until their retention and verification obligations end.
- Subscription owners remain privileged infrastructure administrators. Their actions require independent
  monitoring; this mechanism does not claim to withstand tenant-owner compromise forever.

## Attacks and failure behavior

The reconciler rejects SQLite tail deletion, sequence gaps, database snapshot rollback, full local hash-chain
recalculation, database replacement, a missing remote middle checkpoint, a remote rollback view, an unavailable
key, signature modification, schema downgrade, and any remote head ahead of or different from SQLite. Unexpected
blobs in the dedicated container also fail closed. Corruption therefore becomes an availability incident instead
of silently accepted history.

Existing SQLite audit rows without a genesis checkpoint are never auto-bootstrapped. A new empty database and empty
container create a signed sequence-zero checkpoint. Migration of existing data requires a separate reviewed
ceremony.

## Residual risks and response

- A stolen active HMAC key plus SQLite write access can create fraudulent future events but cannot alter already
  locked blobs. Rotate additively, investigate the first unauthorized sequence, and retain old verification keys.
- Blob/service unavailability makes `/readyz` return 503 and blocks administrative mutation. Restore the trust
  boundary; never bypass it by disabling checkpoint mode.
- `file` and `memory` adapters are explicit local test facilities and are rejected in production.
- Retention expiry or an infrastructure-owner action can weaken long-term evidence. Monitor lock state and retention
  outside the application and retain reviewed release evidence.

