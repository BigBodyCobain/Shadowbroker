# Route Auth Inventory (static scan)

Generated statically by `scripts/route_auth_inventory.py`. This is a static heuristic (not runtime introspection). It detects per-route Depends hints and APIRouter(dependencies=...). Review UNCLASSIFIED and depends-other routes manually.

Classification legend:

- `admin/scoped`, `local-operator`, `openclaw-or-local`, `peer-hmac`: explicit `Depends(...)` or in-handler HMAC verification.
- `signed-write`: signed-envelope enforcement (decorator or handler helper).
- `handler-auth (scoped/session)`: authorization performed inside the handler (scoped token, WS credential).
- `peer-gossip (signed events)`: peer gossip endpoint accepting only hashchain-validated events.
- `public-intentional (read-only)`: GET endpoints with no state change, open by design.
- `public-intentional`: reviewed non-GET endpoint that is a dry run, pure computation, or fixed-upstream proxy.

- Files scanned: 28
- Routes found: 553
- UNCLASSIFIED: 0

| Method | Path | Handler | Auth classification | File |
|---|---|---|---|---|
| GET | `/api/refresh` | `force_refresh` | admin/scoped |  | `backend/main.py` |
| POST | `/api/ais/feed` | `ais_feed` | local-operator |  | `backend/main.py` |
| POST | `/api/viewport` | `update_viewport` | public-intentional |  | `backend/main.py` |
| POST | `/api/layers` | `update_layers` | local-operator |  | `backend/main.py` |
| GET | `/api/oracle/region-intel` | `oracle_region_intel` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/thermal/verify` | `thermal_verify` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/sigint/transmit` | `sigint_transmit` | local-operator |  | `backend/main.py` |
| GET | `/api/sigint/nearest-sdr` | `nearest_sdr` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/send` | `mesh_send` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/log` | `mesh_log` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/status` | `mesh_status` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/signals` | `mesh_signals` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/messages` | `mesh_messages` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/channels` | `mesh_channels` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/vote` | `mesh_vote` | signed-write |  | `backend/main.py` |
| POST | `/api/mesh/report` | `mesh_report` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/reputation` | `mesh_reputation` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/reputation/batch` | `mesh_reputation_batch` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/reputation/all` | `mesh_reputation_all` | admin/scoped |  | `backend/main.py` |
| POST | `/api/mesh/identity/rotate` | `mesh_identity_rotate` | signed-write |  | `backend/main.py` |
| POST | `/api/mesh/identity/revoke` | `mesh_identity_revoke` | signed-write |  | `backend/main.py` |
| POST | `/api/mesh/gate/create` | `gate_create` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/gate/list` | `gate_list` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/gate/{gate_id}` | `gate_detail` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/gate/{gate_id}/message` | `gate_message` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/infonet/status` | `infonet_status` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/privacy/claims` | `api_privacy_claims` | local-operator |  | `backend/main.py` |
| GET | `/api/mesh/infonet/merkle` | `infonet_merkle` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/locator` | `infonet_locator` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/infonet/sync` | `infonet_sync_post` | peer-gossip (signed events) |  | `backend/main.py` |
| GET | `/api/mesh/metrics` | `mesh_metrics` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/rns/status` | `mesh_rns_status` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/sync` | `infonet_sync` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/infonet/ingest` | `infonet_ingest` | admin/scoped |  | `backend/main.py` |
| GET | `/api/mesh/infonet/peer-registry` | `infonet_peer_registry` | local-operator |  | `backend/main.py` |
| GET | `/api/mesh/infonet/bootstrap-manifest` | `infonet_bootstrap_manifest` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/infonet/peer-announce` | `infonet_peer_announce` | peer-hmac |  | `backend/main.py` |
| POST | `/api/mesh/infonet/peer-push` | `infonet_peer_push` | peer-hmac |  | `backend/main.py` |
| POST | `/api/mesh/gate/peer-push` | `gate_peer_push` | peer-hmac |  | `backend/main.py` |
| POST | `/api/mesh/gate/peer-pull` | `gate_peer_pull` | peer-hmac |  | `backend/main.py` |
| GET | `/api/mesh/peers` | `list_peers` | local-operator |  | `backend/main.py` |
| POST | `/api/mesh/peers` | `add_peer` | local-operator |  | `backend/main.py` |
| DELETE | `/api/mesh/peers` | `remove_peer` | local-operator |  | `backend/main.py` |
| PATCH | `/api/mesh/peers` | `toggle_peer` | local-operator |  | `backend/main.py` |
| PUT | `/api/mesh/gate/{gate_id}/envelope_policy` | `set_gate_envelope_policy` | handler-auth (scoped) |  | `backend/main.py` |
| PUT | `/api/mesh/gate/{gate_id}/legacy_envelope_fallback` | `set_gate_legacy_envelope_fallback` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/gate/{gate_id}/messages` | `gate_messages` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/messages` | `infonet_messages` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/messages/wait` | `infonet_messages_wait` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/event/{event_id}` | `infonet_event` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/node/{node_id}` | `infonet_node_events` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/infonet/events` | `infonet_events_by_type` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/oracle/predict` | `oracle_predict` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/oracle/markets` | `oracle_markets` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/oracle/search` | `oracle_search` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/mesh/oracle/markets/more` | `oracle_markets_more` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/oracle/resolve` | `oracle_resolve` | admin/scoped |  | `backend/main.py` |
| GET | `/api/mesh/oracle/consensus` | `oracle_consensus` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/mesh/oracle/stake` | `oracle_stake` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/oracle/stakes/{message_id}` | `oracle_stakes_for_message` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/oracle/profile` | `oracle_profile` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/oracle/predictions` | `oracle_predictions` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/mesh/oracle/resolve-stakes` | `oracle_resolve_stakes` | admin/scoped |  | `backend/main.py` |
| POST | `/api/mesh/dm/register` | `dm_register_key` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/dm/pubkey` | `dm_get_pubkey` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/mesh/dm/prekey-bundle` | `dm_get_prekey_bundle` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/mesh/dm/send` | `dm_send` | signed-write |  | `backend/main.py` |
| POST | `/api/mesh/dm/poll` | `dm_poll_secure` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/dm/poll` | `dm_poll` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/mesh/dm/count` | `dm_count_secure` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/dm/count` | `dm_count` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/mesh/dm/block` | `dm_block` | signed-write |  | `backend/main.py` |
| POST | `/api/mesh/dm/witness` | `dm_key_witness` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/dm/witness` | `dm_key_witness_get` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/mesh/trust/vouch` | `trust_vouch` | signed-write |  | `backend/main.py` |
| GET | `/api/mesh/trust/vouches` | `trust_vouches` | admin/scoped |  | `backend/main.py` |
| GET | `/api/debug-latest` | `debug_latest_data` | admin/scoped |  | `backend/main.py` |
| GET | `/api/cctv/media` | `cctv_media_proxy` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/health` | `health_check` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/top` | `get_top_radios` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/openmhz/systems` | `api_get_openmhz_systems` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/openmhz/calls/{sys_name}` | `api_get_openmhz_calls` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/openmhz/audio` | `api_get_openmhz_audio` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/nearest` | `api_get_nearest_radio` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/radio/nearest-list` | `api_get_nearest_radios_list` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/route/{callsign}` | `get_flight_route` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/region-dossier` | `api_region_dossier` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/geocode/search` | `api_geocode_search` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/geocode/reverse` | `api_geocode_reverse` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/sentinel2/search` | `api_sentinel2_search` | public-intentional (read-only) |  | `backend/main.py` |
| POST | `/api/sentinel/token` | `api_sentinel_token` | public-intentional |  | `backend/main.py` |
| POST | `/api/sentinel/tile` | `api_sentinel_tile` | local-operator |  | `backend/main.py` |
| GET | `/api/settings/api-keys` | `api_get_keys` | admin/scoped |  | `backend/main.py` |
| GET | `/api/settings/api-keys/meta` | `api_get_keys_meta` | public-intentional |  | `backend/main.py` |
| GET | `/api/basemap-config` | `api_basemap_config` | public-intentional (read-only) |  | `backend/main.py` |
| GET | `/api/tools/shodan/status` | `api_shodan_status` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/shodan/search` | `api_shodan_search` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/shodan/count` | `api_shodan_count` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/shodan/host` | `api_shodan_host` | local-operator |  | `backend/main.py` |
| GET | `/api/tools/uw/status` | `api_uw_status` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/uw/congress` | `api_uw_congress` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/uw/darkpool` | `api_uw_darkpool` | local-operator |  | `backend/main.py` |
| POST | `/api/tools/uw/flow` | `api_uw_flow` | local-operator |  | `backend/main.py` |
| GET | `/api/settings/news-feeds` | `api_get_news_feeds` | local-operator |  | `backend/main.py` |
| PUT | `/api/settings/news-feeds` | `api_save_news_feeds` | admin/scoped |  | `backend/main.py` |
| POST | `/api/settings/news-feeds/reset` | `api_reset_news_feeds` | admin/scoped |  | `backend/main.py` |
| GET | `/api/settings/node` | `api_get_node_settings` | handler-auth (scoped) |  | `backend/main.py` |
| PUT | `/api/settings/node` | `api_set_node_settings` | local-operator |  | `backend/main.py` |
| POST | `/api/mesh/infonet/swarm/join` | `infonet_swarm_join` | local-operator |  | `backend/main.py` |
| GET | `/api/settings/wormhole` | `api_get_wormhole_settings` | handler-auth (scoped) |  | `backend/main.py` |
| PUT | `/api/settings/wormhole` | `api_set_wormhole_settings` | admin/scoped |  | `backend/main.py` |
| GET | `/api/settings/privacy-profile` | `api_get_privacy_profile` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/settings/wormhole-status` | `api_get_wormhole_status` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/wormhole/join` | `api_wormhole_join` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/leave` | `api_wormhole_leave` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/identity` | `api_wormhole_identity` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/identity/bootstrap` | `api_wormhole_identity_bootstrap` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/identity` | `api_wormhole_dm_identity` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/invite` | `api_wormhole_dm_invite` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/invite/handles` | `api_wormhole_dm_invite_handles` | local-operator |  | `backend/main.py` |
| DELETE | `/api/wormhole/dm/invite/handles/{handle}` | `api_wormhole_dm_invite_handle_revoke` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/dm/invite/import` | `api_wormhole_dm_invite_import` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-distribution` | `api_wormhole_dm_root_distribution` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/dm/root-witnesses/import` | `api_wormhole_dm_root_witness_import` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/root-witnesses/import-config` | `api_wormhole_dm_root_witness_import_config` | admin/scoped |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-transparency` | `api_wormhole_dm_root_transparency` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-health` | `api_wormhole_dm_root_health` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-health/runbook` | `api_wormhole_dm_root_health_runbook` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-health/alerts` | `api_wormhole_dm_root_health_alerts` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-transparency/ledger` | `api_wormhole_dm_root_transparency_ledger` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/dm/root-transparency/ledger/publish` | `api_wormhole_dm_root_transparency_ledger_publish` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/dm/root-transparency/ledger/published` | `api_wormhole_dm_root_transparency_ledger_published` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/sign` | `api_wormhole_sign` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/enter` | `api_wormhole_gate_enter` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/leave` | `api_wormhole_gate_leave` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/gate/{gate_id}/identity` | `api_wormhole_gate_identity` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/gate/{gate_id}/personas` | `api_wormhole_gate_personas` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/gate/{gate_id}/key` | `api_wormhole_gate_key_status` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/key/rotate` | `api_wormhole_gate_key_rotate` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/persona/create` | `api_wormhole_gate_persona_create` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/persona/activate` | `api_wormhole_gate_persona_activate` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/persona/clear` | `api_wormhole_gate_persona_clear` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/persona/retire` | `api_wormhole_gate_persona_retire` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/key/grant` | `api_wormhole_gate_key_grant` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/message/compose` | `api_wormhole_gate_message_compose` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/message/sign-encrypted` | `api_wormhole_gate_message_sign_encrypted` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/message/post-encrypted` | `api_wormhole_gate_message_post_encrypted` | signed-write |  | `backend/main.py` |
| POST | `/api/wormhole/gate/message/post` | `api_wormhole_gate_message_post` | signed-write |  | `backend/main.py` |
| POST | `/api/wormhole/gate/message/decrypt` | `api_wormhole_gate_message_decrypt` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/messages/decrypt` | `api_wormhole_gate_messages_decrypt` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/state/export` | `api_wormhole_gate_state_export` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/gate/proof` | `api_wormhole_gate_proof` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/sign-raw` | `api_wormhole_sign_raw` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/dm/register-key` | `api_wormhole_dm_register_key` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/prekey/register` | `api_wormhole_dm_prekey_register` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/bootstrap-encrypt` | `api_wormhole_dm_bootstrap_encrypt` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/bootstrap-decrypt` | `api_wormhole_dm_bootstrap_decrypt` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/sender-token` | `api_wormhole_dm_sender_token` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/dm/open-seal` | `api_wormhole_dm_open_seal` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/build-seal` | `api_wormhole_dm_build_seal` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/dead-drop-token` | `api_wormhole_dm_dead_drop_token` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/pairwise-alias` | `api_wormhole_dm_pairwise_alias` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/pairwise-alias/rotate` | `api_wormhole_dm_pairwise_alias_rotate` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/dead-drop-tokens` | `api_wormhole_dm_dead_drop_tokens` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/sas` | `api_wormhole_dm_sas` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/sas/confirm` | `api_wormhole_dm_sas_confirm` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/sas/acknowledge` | `api_wormhole_dm_sas_acknowledge` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/sas/recover-root` | `api_wormhole_dm_sas_recover_root` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/encrypt` | `api_wormhole_dm_encrypt` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/compose` | `api_wormhole_dm_compose` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/decrypt` | `api_wormhole_dm_decrypt` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/reset` | `api_wormhole_dm_reset` | admin/scoped |  | `backend/main.py` |
| GET | `/api/wormhole/dm/contacts` | `api_wormhole_dm_contacts` | admin/scoped |  | `backend/main.py` |
| PUT | `/api/wormhole/dm/contact` | `api_wormhole_dm_contact_put` | admin/scoped |  | `backend/main.py` |
| DELETE | `/api/wormhole/dm/contact/{peer_id}` | `api_wormhole_dm_contact_delete` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/dm/contact/{peer_id}/sever` | `api_wormhole_dm_contact_sever` | admin/scoped |  | `backend/main.py` |
| GET | `/api/wormhole/status` | `api_wormhole_status` | handler-auth (scoped) |  | `backend/main.py` |
| GET | `/api/wormhole/review-export` | `api_wormhole_review_export` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/review-manifest` | `api_wormhole_review_manifest` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/review-consistency` | `api_wormhole_review_consistency` | local-operator |  | `backend/main.py` |
| GET | `/api/wormhole/health` | `api_wormhole_health` | handler-auth (scoped) |  | `backend/main.py` |
| POST | `/api/wormhole/connect` | `api_wormhole_connect` | local-operator |  | `backend/main.py` |
| POST | `/api/wormhole/disconnect` | `api_wormhole_disconnect` | admin/scoped |  | `backend/main.py` |
| POST | `/api/wormhole/restart` | `api_wormhole_restart` | admin/scoped |  | `backend/main.py` |
| PUT | `/api/settings/privacy-profile` | `api_set_privacy_profile` | admin/scoped |  | `backend/main.py` |
| POST | `/api/system/update` | `system_update` | admin/scoped |  | `backend/main.py` |
| GET | `/api/settings/api-keys` | `api_get_keys` | local-operator |  | `backend/routers/admin.py` |
| PUT | `/api/settings/api-keys` | `api_save_keys` | local-operator |  | `backend/routers/admin.py` |
| GET | `/api/settings/api-keys/meta` | `api_get_keys_meta` | public-intentional |  | `backend/routers/admin.py` |
| GET | `/api/settings/operator-handle` | `api_get_operator_handle` | local-operator |  | `backend/routers/admin.py` |
| GET | `/api/settings/news-feeds` | `api_get_news_feeds` | local-operator |  | `backend/routers/admin.py` |
| PUT | `/api/settings/news-feeds` | `api_save_news_feeds` | admin/scoped |  | `backend/routers/admin.py` |
| POST | `/api/settings/news-feeds/reset` | `api_reset_news_feeds` | admin/scoped |  | `backend/routers/admin.py` |
| GET | `/api/settings/node` | `api_get_node_settings` | handler-auth (scoped) |  | `backend/routers/admin.py` |
| PUT | `/api/settings/node` | `api_set_node_settings` | local-operator |  | `backend/routers/admin.py` |
| GET | `/api/settings/meshtastic-mqtt` | `api_get_meshtastic_mqtt_settings` | local-operator |  | `backend/routers/admin.py` |
| PUT | `/api/settings/meshtastic-mqtt` | `api_set_meshtastic_mqtt_settings` | local-operator |  | `backend/routers/admin.py` |
| GET | `/api/settings/timemachine` | `api_get_timemachine_settings` | local-operator |  | `backend/routers/admin.py` |
| PUT | `/api/settings/timemachine` | `api_set_timemachine_settings` | local-operator |  | `backend/routers/admin.py` |
| POST | `/api/system/update` | `system_update` | admin/scoped |  | `backend/routers/admin.py` |
| GET | `/api/settings/tor` | `api_tor_status` | local-operator |  | `backend/routers/admin.py` |
| POST | `/api/settings/tor/start` | `api_tor_start` | local-operator |  | `backend/routers/admin.py` |
| POST | `/api/settings/tor/reset-identity` | `api_tor_reset_identity` | local-operator |  | `backend/routers/admin.py` |
| POST | `/api/settings/agent/reset-all` | `api_reset_all_agent_credentials` | local-operator |  | `backend/routers/admin.py` |
| POST | `/api/settings/tor/stop` | `api_tor_stop` | local-operator |  | `backend/routers/admin.py` |
| GET | `/api/agent-shell/settings` | `read_agent_shell_settings` | local-operator |  | `backend/routers/agent_shell.py` |
| POST | `/api/agent-shell/ws-token` | `mint_agent_shell_ws_token_route` | local-operator |  | `backend/routers/agent_shell.py` |
| PUT | `/api/agent-shell/settings` | `write_agent_shell_settings` | local-operator |  | `backend/routers/agent_shell.py` |
| WEBSOCKET | `/api/agent-shell/ws` | `agent_shell_websocket` | handler-auth (session) |  | `backend/routers/agent_shell.py` |
| GET | `/api/ai/status` | `ai_status` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/pins` | `create_pin` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/pins/batch` | `create_pins_batch` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/pins` | `list_pins` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/pins/geojson` | `pins_geojson` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/pins/{pin_id}` | `get_pin_detail` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| PATCH | `/api/ai/pins/{pin_id}` | `patch_pin` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/pins/{pin_id}/comments` | `post_pin_comment` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/pins/{pin_id}/comments/{comment_id}` | `delete_pin_comment_route` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/pins/{pin_id}` | `delete_pin` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/pins` | `clear_pins` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/layers` | `api_create_layer` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/layers` | `api_list_layers` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| PATCH | `/api/ai/layers/{layer_id}` | `api_update_layer` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/layers/{layer_id}` | `api_delete_layer` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/layers/{layer_id}/refresh` | `api_refresh_layer_feed` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| PUT | `/api/ai/layer-overrides` | `put_layer_overrides` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/layer-overrides` | `read_layer_overrides` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/layer-overrides` | `delete_layer_overrides` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/agent-actions` | `get_agent_actions` | local-operator |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/satellite-images` | `ai_satellite_images` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/news-near` | `ai_news_near` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/inject` | `inject_data` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/inject` | `remove_injected` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/report` | `generate_report` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/summary` | `ai_telemetry_summary` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/timemachine/snapshot` | `take_snapshot` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/snapshots` | `list_snapshots` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/snapshot/{snapshot_id}` | `get_snapshot` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/hourly-index` | `timemachine_hourly_index` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/playback/{snapshot_id}` | `timemachine_playback` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/timemachine/snapshots` | `clear_snapshots` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/config` | `get_timemachine_config` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| PUT | `/api/ai/timemachine/config` | `update_timemachine_config` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/timemachine/diff` | `diff_snapshots` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/ai/news/summary` | `ai_news_summary` | public-intentional (read-only) |  | `backend/routers/ai_intel.py` |
| GET | `/ai/correlations/explain` | `ai_correlation_explanations` | public-intentional (read-only) |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/tools` | `agent_tool_manifest` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/capabilities` | `api_capabilities` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/connect-info` | `get_connect_info` | local-operator |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/connect-info/bootstrap` | `bootstrap_hmac_secret` | local-operator |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/connect-info/reveal` | `reveal_hmac_secret` | local-operator |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/connect-info/regenerate` | `regenerate_hmac_secret` | local-operator |  | `backend/routers/ai_intel.py` |
| PUT | `/api/ai/connect-info/access-tier` | `set_access_tier` | local-operator |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/agent-identity` | `get_agent_identity` | local-operator |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/agent-identity/bootstrap` | `bootstrap_agent_identity` | local-operator |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/agent-identity` | `revoke_agent_identity` | local-operator |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/channel/command` | `channel_submit_command` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/channel/batch` | `channel_submit_batch` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/channel/poll` | `channel_poll` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| POST | `/api/ai/channel/task` | `channel_push_task` | local-operator |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/channel/status` | `channel_status` | local-operator |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/channel/sse` | `channel_sse` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| WEBSOCKET | `/api/ai/channel/ws` | `channel_websocket` | handler-auth (session) |  | `backend/routers/ai_intel.py` |
| DELETE | `/api/ai/analysis-zones/{zone_id}` | `delete_analysis_zone` | local-operator |  | `backend/routers/ai_intel.py` |
| GET | `/api/ai/analysis-zones` | `list_analysis_zones` | openclaw-or-local |  | `backend/routers/ai_intel.py` |
| GET | `/api/analytics/risk_heatmap` | `risk_heatmap_get` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| POST | `/api/analytics/risk_heatmap` | `risk_heatmap_post` | local-operator |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/dossier/{region}` | `analytics_dossier` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/backtest` | `analytics_backtest` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/rolling` | `analytics_rolling` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/alerts` | `analytics_top_alerts` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/rolling/micro` | `analytics_rolling_micro` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| GET | `/api/analytics/rolling/{week_id}` | `analytics_rolling_week` | public-intentional (read-only) |  | `backend/routers/analytics.py` |
| POST | `/api/analytics/rolling/freeze` | `analytics_rolling_freeze` | local-operator |  | `backend/routers/analytics.py` |
| POST | `/api/analytics/rolling/label` | `analytics_rolling_label` | local-operator |  | `backend/routers/analytics.py` |
| GET | `/api/cctv/media` | `cctv_media_proxy` | public-intentional (read-only) |  | `backend/routers/cctv.py` |
| GET | `/api/refresh` | `force_refresh` | admin/scoped |  | `backend/routers/data.py` |
| POST | `/api/ais/feed` | `ais_feed` | local-operator |  | `backend/routers/data.py` |
| GET | `/api/trail/flight/{icao24}` | `get_selected_flight_trail` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/trail/ship/{mmsi}` | `get_selected_ship_trail` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/aviation/datalink/status` | `aviation_datalink_status` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/aviation/datalink/messages` | `aviation_datalink_messages` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/sigint/meshtastic/status` | `meshtastic_map_status` | public-intentional (read-only) |  | `backend/routers/data.py` |
| POST | `/api/sigint/meshtastic/scan` | `meshtastic_planet_scan` | local-operator |  | `backend/routers/data.py` |
| POST | `/api/viewport` | `update_viewport` | public-intentional |  | `backend/routers/data.py` |
| GET | `/api/liveuamap/scraper-status` | `api_liveuamap_scraper_status` | local-operator |  | `backend/routers/data.py` |
| POST | `/api/liveuamap/scraper-opt-in` | `api_liveuamap_scraper_opt_in` | local-operator |  | `backend/routers/data.py` |
| GET | `/api/prediction-markets/status` | `api_prediction_markets_status` | local-operator |  | `backend/routers/data.py` |
| POST | `/api/prediction-markets/opt-in` | `api_prediction_markets_opt_in` | local-operator |  | `backend/routers/data.py` |
| GET | `/api/layers` | `get_layers` | public-intentional (read-only) |  | `backend/routers/data.py` |
| POST | `/api/layers` | `update_layers` | local-operator |  | `backend/routers/data.py` |
| GET | `/api/live-data` | `live_data` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/bootstrap/critical` | `bootstrap_critical` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/live-data/fast` | `live_data_fast` | public-intentional (read-only) |  | `backend/routers/data.py` |
| GET | `/api/live-data/slow` | `live_data_slow` | public-intentional (read-only) |  | `backend/routers/data.py` |
| POST | `/api/satellites/overflights` | `satellite_overflights` | public-intentional |  | `backend/routers/data.py` |
| GET | `/api/entity/expand` | `entity_expand` | local-operator |  | `backend/routers/entity_graph.py` |
| GET | `/api/health` | `health_check` | public-intentional (read-only) |  | `backend/routers/health.py` |
| GET | `/api/summary` | `summary` | public-intentional (read-only) |  | `backend/routers/health.py` |
| GET | `/api/debug-latest` | `debug_latest_data` | admin/scoped |  | `backend/routers/health.py` |
| GET | `/status` | `infonet_status` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/petitions` | `list_petitions` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/petitions/{petition_id}` | `get_petition` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| POST | `/petitions/preview` | `preview_petition_payload` | public-intentional |  | `backend/routers/infonet.py` |
| POST | `/events/validate` | `validate_event` | public-intentional |  | `backend/routers/infonet.py` |
| GET | `/upgrades` | `list_upgrades` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/upgrades/{proposal_id}` | `get_upgrade` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/markets/{market_id}` | `get_market_state` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/markets/{market_id}/preview-resolution` | `preview_resolution` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/gates/{gate_id}` | `get_gate_state` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/nodes/{node_id}/reputation` | `get_node_reputation` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/bootstrap/markets/{market_id}` | `get_bootstrap_market_state` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| POST | `/append` | `append_event` | signed-write (handler) |  | `backend/routers/infonet.py` |
| GET | `/function-keys/operator/{operator_id}/batch-summary` | `operator_batch_summary` | public-intentional (read-only) |  | `backend/routers/infonet.py` |
| GET | `/api/malware` | `malware_feed` | public-intentional (read-only) |  | `backend/routers/intel_feeds.py` |
| GET | `/api/cyber-threats` | `cyber_threats` | public-intentional (read-only) |  | `backend/routers/intel_feeds.py` |
| GET | `/api/country-risk` | `country_risk` | public-intentional (read-only) |  | `backend/routers/intel_feeds.py` |
| GET | `/api/telegram-feed` | `telegram_feed` | public-intentional (read-only) |  | `backend/routers/intel_feeds.py` |
| GET | `/api/telegram/media` | `telegram_media_proxy` | public-intentional (read-only) |  | `backend/routers/intel_feeds.py` |
| POST | `/api/mesh/dm/register` | `dm_register_key` | signed-write |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/dm/pubkey` | `dm_get_pubkey` | public-intentional (read-only) |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/dm/prekey-bundle` | `dm_get_prekey_bundle` | public-intentional (read-only) |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/prekey-peer-lookup` | `dm_prekey_peer_lookup` | peer-hmac |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/send` | `dm_send` | signed-write |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/poll` | `dm_poll_secure` | signed-write |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/dm/poll` | `dm_poll` | public-intentional (read-only) |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/count` | `dm_count_secure` | signed-write |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/dm/count` | `dm_count` | public-intentional (read-only) |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/block` | `dm_block` | signed-write |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/dm/witness` | `dm_key_witness` | signed-write |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/dm/witness` | `dm_key_witness_get` | handler-auth (scoped) |  | `backend/routers/mesh_dm.py` |
| POST | `/api/mesh/trust/vouch` | `trust_vouch` | signed-write |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/trust/vouches` | `trust_vouches` | admin/scoped |  | `backend/routers/mesh_dm.py` |
| GET | `/api/mesh/peers` | `list_peers` | local-operator |  | `backend/routers/mesh_operator.py` |
| POST | `/api/mesh/peers` | `add_peer` | local-operator |  | `backend/routers/mesh_operator.py` |
| DELETE | `/api/mesh/peers` | `remove_peer` | local-operator |  | `backend/routers/mesh_operator.py` |
| PATCH | `/api/mesh/peers` | `toggle_peer` | local-operator |  | `backend/routers/mesh_operator.py` |
| POST | `/api/mesh/oracle/predict` | `oracle_predict` | signed-write |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/markets` | `oracle_markets` | public-intentional (read-only) |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/search` | `oracle_search` | public-intentional (read-only) |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/markets/more` | `oracle_markets_more` | public-intentional (read-only) |  | `backend/routers/mesh_oracle.py` |
| POST | `/api/mesh/oracle/resolve` | `oracle_resolve` | admin/scoped |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/consensus` | `oracle_consensus` | public-intentional (read-only) |  | `backend/routers/mesh_oracle.py` |
| POST | `/api/mesh/oracle/stake` | `oracle_stake` | signed-write |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/stakes/{message_id}` | `oracle_stakes_for_message` | handler-auth (scoped) |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/profile` | `oracle_profile` | handler-auth (scoped) |  | `backend/routers/mesh_oracle.py` |
| GET | `/api/mesh/oracle/predictions` | `oracle_predictions` | handler-auth (scoped) |  | `backend/routers/mesh_oracle.py` |
| POST | `/api/mesh/oracle/resolve-stakes` | `oracle_resolve_stakes` | admin/scoped |  | `backend/routers/mesh_oracle.py` |
| POST | `/api/mesh/infonet/peer-push` | `infonet_peer_push` | peer-hmac |  | `backend/routers/mesh_peer_sync.py` |
| POST | `/api/mesh/dm/replicate-envelope` | `dm_replicate_envelope` | peer-hmac |  | `backend/routers/mesh_peer_sync.py` |
| POST | `/api/mesh/gate/peer-push` | `gate_peer_push` | peer-hmac |  | `backend/routers/mesh_peer_sync.py` |
| POST | `/api/mesh/gate/peer-pull` | `gate_peer_pull` | peer-hmac |  | `backend/routers/mesh_peer_sync.py` |
| POST | `/api/mesh/send` | `mesh_send` | signed-write |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/meshtastic/send` | `meshtastic_public_send` | local-operator |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/log` | `mesh_log` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/status` | `mesh_status` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/signals` | `mesh_signals` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/messages` | `mesh_messages` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/channels` | `mesh_channels` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/vote` | `mesh_vote` | signed-write |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/report` | `mesh_report` | signed-write |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/reputation` | `mesh_reputation` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/reputation/batch` | `mesh_reputation_batch` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/reputation/all` | `mesh_reputation_all` | admin/scoped |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/identity/rotate` | `mesh_identity_rotate` | signed-write |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/identity/revoke` | `mesh_identity_revoke` | signed-write |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/gate/create` | `gate_create` | signed-write |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/gate/list` | `gate_list` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/gate/{gate_id}` | `gate_detail` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/gate/{gate_id}/message` | `gate_message` | signed-write |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/status` | `infonet_status` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/merkle` | `infonet_merkle` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/locator` | `infonet_locator` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/infonet/sync` | `infonet_sync_post` | peer-gossip (signed events) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/metrics` | `mesh_metrics` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/rns/status` | `mesh_rns_status` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/sync` | `infonet_sync` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/infonet/ingest` | `infonet_ingest` | admin/scoped |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/peers` | `list_peers` | local-operator |  | `backend/routers/mesh_public.py` |
| POST | `/api/mesh/peers` | `add_peer` | local-operator |  | `backend/routers/mesh_public.py` |
| DELETE | `/api/mesh/peers` | `remove_peer` | local-operator |  | `backend/routers/mesh_public.py` |
| PATCH | `/api/mesh/peers` | `toggle_peer` | local-operator |  | `backend/routers/mesh_public.py` |
| PUT | `/api/mesh/gate/{gate_id}/envelope_policy` | `set_gate_envelope_policy` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| PUT | `/api/mesh/gate/{gate_id}/legacy_envelope_fallback` | `set_gate_legacy_envelope_fallback` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/gate/{gate_id}/messages` | `gate_messages` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/messages` | `infonet_messages` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/messages/wait` | `infonet_messages_wait` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/session-stream` | `infonet_session_stream` | admin/scoped |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/event/{event_id}` | `infonet_event` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/node/{node_id}` | `infonet_node_events` | handler-auth (scoped) |  | `backend/routers/mesh_public.py` |
| GET | `/api/mesh/infonet/events` | `infonet_events_by_type` | public-intentional (read-only) |  | `backend/routers/mesh_public.py` |
| GET | `/missions/config` | `configuration` | local-operator (router-default) |  | `backend/routers/missions.py` |
| GET | `/missions` | `index` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions` | `create` | local-operator (router-default) |  | `backend/routers/missions.py` |
| GET | `/missions/{mission_id}` | `read` | local-operator (router-default) |  | `backend/routers/missions.py` |
| DELETE | `/missions/{mission_id}` | `delete` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/control` | `control` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/advance` | `advance` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/client-start` | `client_start` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/receipt` | `receipt` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/approve` | `approve` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/missions/{mission_id}/evidence/{evidence_id}` | `pin` | local-operator (router-default) |  | `backend/routers/missions.py` |
| GET | `/watches` | `watches` | local-operator (router-default) |  | `backend/routers/missions.py` |
| POST | `/watches` | `create_watch` | local-operator (router-default) |  | `backend/routers/missions.py` |
| PATCH | `/watches/{watch_id}` | `pause_watch` | local-operator (router-default) |  | `backend/routers/missions.py` |
| DELETE | `/watches/{watch_id}` | `delete_watch` | local-operator (router-default) |  | `backend/routers/missions.py` |
| GET | `/api/osint/ip` | `osint_ip` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/dns` | `osint_dns` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/whois` | `osint_whois` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/certs` | `osint_certs` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/threats` | `osint_threats` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/bgp` | `osint_bgp` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/sanctions` | `osint_sanctions` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/cve` | `osint_cve` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/mac` | `osint_mac` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/github` | `osint_github` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/leaks` | `osint_leaks` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osint/sweep` | `osint_sweep_init` | local-operator (router-default) |  | `backend/routers/osint.py` |
| POST | `/api/osint/sweep/scan` | `osint_sweep_scan` | local-operator (router-default) |  | `backend/routers/osint.py` |
| GET | `/api/osm-tile/{z}/{x}/{y}.png` | `osm_tile` | public-intentional (read-only) |  | `backend/routers/osm_tiles.py` |
| GET | `/api/radio/top` | `get_top_radios` | public-intentional (read-only) |  | `backend/routers/radio.py` |
| GET | `/api/radio/openmhz/systems` | `api_get_openmhz_systems` | local-operator |  | `backend/routers/radio.py` |
| GET | `/api/radio/openmhz/calls/{sys_name}` | `api_get_openmhz_calls` | local-operator |  | `backend/routers/radio.py` |
| GET | `/api/radio/openmhz/audio` | `api_get_openmhz_audio` | local-operator |  | `backend/routers/radio.py` |
| GET | `/api/radio/nearest` | `api_get_nearest_radio` | public-intentional (read-only) |  | `backend/routers/radio.py` |
| GET | `/api/radio/nearest-list` | `api_get_nearest_radios_list` | public-intentional (read-only) |  | `backend/routers/radio.py` |
| GET | `/api/route/{callsign}` | `get_flight_route` | public-intentional (read-only) |  | `backend/routers/radio.py` |
| GET | `/api/road-corridors/status` | `road_corridors_status` | public-intentional (read-only) |  | `backend/routers/road_corridors.py` |
| GET | `/api/road-corridors` | `list_road_corridors` | public-intentional (read-only) |  | `backend/routers/road_corridors.py` |
| POST | `/api/road-corridors/analyze` | `analyze_road_corridor_here` | public-intentional |  | `backend/routers/road_corridors.py` |
| GET | `/api/road-corridors/analyze/status` | `analyze_road_corridor_status` | public-intentional (read-only) |  | `backend/routers/road_corridors.py` |
| GET | `/api/road-corridors/{preset_id}` | `get_road_corridor` | public-intentional (read-only) |  | `backend/routers/road_corridors.py` |
| GET | `/api/sar/status` | `sar_status` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| GET | `/api/sar/anomalies` | `sar_anomalies` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| GET | `/api/sar/scenes` | `sar_scenes` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| GET | `/api/sar/coverage` | `sar_coverage` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| GET | `/api/sar/near` | `sar_near` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| GET | `/api/sar/aois` | `sar_aoi_list` | public-intentional (read-only) |  | `backend/routers/sar.py` |
| POST | `/api/sar/aois` | `sar_aoi_upsert` | local-operator |  | `backend/routers/sar.py` |
| DELETE | `/api/sar/aois/{aoi_id}` | `sar_aoi_delete` | local-operator |  | `backend/routers/sar.py` |
| POST | `/api/sar/mode-b/enable` | `sar_mode_b_enable` | local-operator |  | `backend/routers/sar.py` |
| POST | `/api/sar/mode-b/disable` | `sar_mode_b_disable` | local-operator |  | `backend/routers/sar.py` |
| GET | `/api/scm-suppliers` | `scm_suppliers` | local-operator |  | `backend/routers/scm.py` |
| GET | `/api/oracle/region-intel` | `oracle_region_intel` | public-intentional (read-only) |  | `backend/routers/sigint.py` |
| GET | `/api/thermal/verify` | `thermal_verify` | local-operator |  | `backend/routers/sigint.py` |
| POST | `/api/sigint/transmit` | `sigint_transmit` | local-operator |  | `backend/routers/sigint.py` |
| GET | `/api/sigint/nearest-sdr` | `nearest_sdr` | public-intentional (read-only) |  | `backend/routers/sigint.py` |
| GET | `/api/region-dossier` | `api_region_dossier` | public-intentional (read-only) |  | `backend/routers/tools.py` |
| GET | `/api/geocode/search` | `api_geocode_search` | public-intentional (read-only) |  | `backend/routers/tools.py` |
| GET | `/api/geocode/reverse` | `api_geocode_reverse` | public-intentional (read-only) |  | `backend/routers/tools.py` |
| GET | `/api/wikipedia/summary` | `api_wikipedia_summary` | public-intentional (read-only) |  | `backend/routers/tools.py` |
| POST | `/api/wikidata/sparql` | `api_wikidata_sparql` | public-intentional |  | `backend/routers/tools.py` |
| GET | `/api/sentinel2/search` | `api_sentinel2_search` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/sentinel/token` | `api_sentinel_token` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/sentinel/tile` | `api_sentinel_tile` | local-operator |  | `backend/routers/tools.py` |
| GET | `/api/tools/shodan/status` | `api_shodan_status` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/shodan/search` | `api_shodan_search` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/shodan/count` | `api_shodan_count` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/shodan/host` | `api_shodan_host` | local-operator |  | `backend/routers/tools.py` |
| GET | `/api/tools/uw/status` | `api_uw_status` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/uw/congress` | `api_uw_congress` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/uw/darkpool` | `api_uw_darkpool` | local-operator |  | `backend/routers/tools.py` |
| POST | `/api/tools/uw/flow` | `api_uw_flow` | local-operator |  | `backend/routers/tools.py` |
| GET | `/api/voice/status` | `voice_status` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/opt-in` | `voice_opt_in` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/provider` | `voice_provider_save` | local-operator |  | `backend/routers/voice.py` |
| GET | `/api/voice/speech-settings` | `read_speech_settings` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/speech-settings` | `save_speech_settings` | local-operator |  | `backend/routers/voice.py` |
| GET | `/api/voice/speech-models` | `speech_models` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/transcribe` | `voice_transcribe` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/session` | `create_voice_session` | local-operator |  | `backend/routers/voice.py` |
| DELETE | `/api/voice/session/{session_id}` | `delete_voice_session` | local-operator |  | `backend/routers/voice.py` |
| WEBSOCKET | `/api/voice/session/ws` | `voice_session_ws` | handler-auth (session) |  | `backend/routers/voice.py` |
| POST | `/api/voice/chat` | `voice_chat` | local-operator |  | `backend/routers/voice.py` |
| GET | `/api/voice/tools` | `voice_tools` | local-operator |  | `backend/routers/voice.py` |
| GET | `/api/voice/models` | `voice_models` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/tool` | `voice_tool` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/hud-summary` | `voice_hud_summary` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/turn` | `voice_turn` | local-operator |  | `backend/routers/voice.py` |
| POST | `/api/voice/interrogate` | `voice_interrogate` | local-operator |  | `backend/routers/voice.py` |
| GET | `/api/settings/wormhole` | `api_get_wormhole_settings` | handler-auth (scoped) |  | `backend/routers/wormhole.py` |
| PUT | `/api/settings/wormhole` | `api_set_wormhole_settings` | admin/scoped |  | `backend/routers/wormhole.py` |
| GET | `/api/settings/privacy-profile` | `api_get_privacy_profile` | handler-auth (scoped) |  | `backend/routers/wormhole.py` |
| GET | `/api/settings/wormhole-status` | `api_get_wormhole_status` | handler-auth (scoped) |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/join` | `api_wormhole_join` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/leave` | `api_wormhole_leave` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/identity` | `api_wormhole_identity` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/identity/bootstrap` | `api_wormhole_identity_bootstrap` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/dm/identity` | `api_wormhole_dm_identity` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/dm/invite` | `api_wormhole_dm_invite` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/dm/invite/handles` | `api_wormhole_dm_invite_handles` | local-operator |  | `backend/routers/wormhole.py` |
| PATCH | `/api/wormhole/dm/invite/handles/{handle}` | `api_wormhole_dm_invite_handle_update` | local-operator |  | `backend/routers/wormhole.py` |
| DELETE | `/api/wormhole/dm/invite/handles/{handle}` | `api_wormhole_dm_invite_handle_revoke` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/invite/import` | `api_wormhole_dm_invite_import` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/sign` | `api_wormhole_sign` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/enter` | `api_wormhole_gate_enter` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/leave` | `api_wormhole_gate_leave` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/gate/{gate_id}/identity` | `api_wormhole_gate_identity` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/gate/{gate_id}/personas` | `api_wormhole_gate_personas` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/gate/{gate_id}/key` | `api_wormhole_gate_key_status` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/key/rotate` | `api_wormhole_gate_key_rotate` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/persona/create` | `api_wormhole_gate_persona_create` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/persona/activate` | `api_wormhole_gate_persona_activate` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/persona/clear` | `api_wormhole_gate_persona_clear` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/persona/retire` | `api_wormhole_gate_persona_retire` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/key/grant` | `api_wormhole_gate_key_grant` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/invite` | `api_wormhole_gate_invite` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/gate/invites` | `api_wormhole_gate_invites` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/invite/accept` | `api_wormhole_gate_invite_accept` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/invite/decline` | `api_wormhole_gate_invite_decline` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/key/rekey` | `api_wormhole_gate_key_rekey` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/gate/{gate_id}/key/sharing` | `api_wormhole_gate_key_sharing` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/message/compose` | `api_wormhole_gate_message_compose` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/message/sign-encrypted` | `api_wormhole_gate_message_sign_encrypted` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/message/post-encrypted` | `api_wormhole_gate_message_post_encrypted` | signed-write (handler) |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/message/post` | `api_wormhole_gate_message_post` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/message/decrypt` | `api_wormhole_gate_message_decrypt` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/messages/decrypt` | `api_wormhole_gate_messages_decrypt` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/state/export` | `api_wormhole_gate_state_export` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/gate/proof` | `api_wormhole_gate_proof` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/sign-raw` | `api_wormhole_sign_raw` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/register-key` | `api_wormhole_dm_register_key` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/prekey/register` | `api_wormhole_dm_prekey_register` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/bootstrap-encrypt` | `api_wormhole_dm_bootstrap_encrypt` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/bootstrap-decrypt` | `api_wormhole_dm_bootstrap_decrypt` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/connect-contact` | `api_wormhole_dm_connect_contact` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/sender-token` | `api_wormhole_dm_sender_token` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/open-seal` | `api_wormhole_dm_open_seal` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/build-seal` | `api_wormhole_dm_build_seal` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/dead-drop-token` | `api_wormhole_dm_dead_drop_token` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/pairwise-alias` | `api_wormhole_dm_pairwise_alias` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/pairwise-alias/rotate` | `api_wormhole_dm_pairwise_alias_rotate` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/dead-drop-tokens` | `api_wormhole_dm_dead_drop_tokens` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/sas` | `api_wormhole_dm_sas` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/encrypt` | `api_wormhole_dm_encrypt` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/compose` | `api_wormhole_dm_compose` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/decrypt` | `api_wormhole_dm_decrypt` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/mls-key-package` | `api_wormhole_dm_mls_key_package` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/mls-reset` | `api_wormhole_dm_mls_reset` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/reset` | `api_wormhole_dm_reset` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/selftest` | `api_wormhole_dm_selftest` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/dm/contacts` | `api_wormhole_dm_contacts` | admin/scoped |  | `backend/routers/wormhole.py` |
| PUT | `/api/wormhole/dm/contact` | `api_wormhole_dm_contact_put` | admin/scoped |  | `backend/routers/wormhole.py` |
| DELETE | `/api/wormhole/dm/contact/{peer_id}` | `api_wormhole_dm_contact_delete` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/dm/contact/{peer_id}/sever` | `api_wormhole_dm_contact_sever` | admin/scoped |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/status` | `api_wormhole_status` | public-intentional (read-only) |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/private-delivery/{item_id}` | `api_wormhole_private_delivery_item` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/private-delivery/{item_id}/action` | `api_wormhole_private_delivery_action` | local-operator |  | `backend/routers/wormhole.py` |
| GET | `/api/wormhole/health` | `api_wormhole_health` | handler-auth (scoped) |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/connect` | `api_wormhole_connect` | local-operator |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/disconnect` | `api_wormhole_disconnect` | admin/scoped |  | `backend/routers/wormhole.py` |
| POST | `/api/wormhole/restart` | `api_wormhole_restart` | admin/scoped |  | `backend/routers/wormhole.py` |
| PUT | `/api/settings/privacy-profile` | `api_set_privacy_profile` | admin/scoped |  | `backend/routers/wormhole.py` |
