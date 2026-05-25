# Changelog

All notable changes to this module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [18.0.1.0.0] - 2026-05-25

### Added

- Initial release. Two-stage MO lifecycle:
  - `mrp.production.stage` Selection (intermediate/prepared), default
    intermediate, copy=False, tracking.
  - `mrp.production.staged_preparation_enabled` related field from
    picking_type for view conditional display.
  - `stock.picking.type.staged_preparation_enabled` boolean flag — per
    manufacturing operation type. Disabled by default → existing flows
    untouched.
- Override `mrp.production._get_move_raw_values` — when stage='intermediate'
  AND enabled: force `location_id = warehouse.lot_stock_id` (bypass
  pbm_loc buffer).
- Override `mrp.production._get_move_finished_values` — same logic for
  `location_dest_id` (bypass sam_loc buffer).
- New action `mrp.production.action_prepare_production` (button "Prepare for
  Production"):
  - Swap raw moves' `location_id` back to `warehouse.pbm_loc_id` (2/3-step)
  - Swap finished moves' `location_dest_id` back to `warehouse.sam_loc_id` (3-step)
  - Auto-create `procurement_group_id` if missing (prevent picking merge across MOs)
  - Re-confirm affected moves via `_action_confirm(merge=False)` to trigger
    pull rules natively → Pick/Store pickings born
  - Idempotent: 1-step warehouse → logical no-op, stage flips прежно
- View extensions:
  - `stock.picking.type` form: Staged Preparation group on General page
    (only visible for `code='mrp_operation'`).
  - `mrp.production` form: stage statusbar widget + "Prepare for Production"
    header button (conditional на enabled + stage='intermediate' + state ∈
    {confirmed, progress}).

### Known limitations

- Reverse transition `prepared → intermediate` not supported (high-risk
  cancel + restore pattern; reserved for future iteration after consultant
  review).
- Multi-level BoM: module acts only on the current MO, not cascading to
  sub-procurements.
