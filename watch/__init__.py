"""
watch/ — Norric Watch: change-detection webhooks on Kreditvakt data.

Phase 1 (this package): company watch core. Customers subscribe to
Kreditvakt-derived change events on Swedish companies; Norric pushes an
HMAC-signed webhook to their callback URL after each daily scoring beat.

Honesty rule (same as the September docs cleanup): an event type is only
offered when its underlying pipeline is live. The four v1 event types all
ride data the Kreditvakt beats already write. Specified-but-blocked types
(annual reports, municipal tenders) are rejected with the blocker named.
"""
