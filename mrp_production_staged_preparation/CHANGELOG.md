# Changelog

All notable changes to this module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [18.0.2.0.0] - 2026-05-26

### Changed (BREAKING)

- Махнат `stage` Selection field. Lifecycle gate-ът сега се изразява чрез
  нова стойност `'preparation'` в нативния `mrp.production.state` Selection
  (между `'confirmed'` и `'progress'`), вмъкната чрез `selection_add`.
- `action_confirm` override: след native confirm flow, MO с
  `staged_preparation_enabled=True` се premества от state `'confirmed'` в
  state `'preparation'`. MO без enabled flag остават в `'confirmed'`.
- `action_prepare_production`: преход `'preparation' → 'confirmed'` (вместо
  `'intermediate' → 'prepared'` както в 18.0.1.x).
- View опростен: премахнат отделен stage statusbar widget. Native state
  statusbar показва `'Preparation'` като нова стъпка автоматично.
- Бутон "Prepare for Production" видим само при `state='preparation'`.
- `_staged_intermediate_active()` сега check-ва `state == 'preparation'`
  вместо `stage == 'intermediate'`.

### Migration note

Деинсталацията използва `ondelete={'preparation': 'set default'}` — при
unins на модула MO-та в state `'preparation'` се recompute-ват от
`_compute_state` спрямо текущото състояние на raw/finished moves (обикновено
обратно към `'confirmed'`).

## [18.0.1.1.0] - 2026-05-26 (superseded by 18.0.2.0.0)

### Fixed

- Pick picking беше раждан въпреки endpoint swap в intermediate stage.
  Причина: `manufacture_mto_pull_id` (глобално MTO правило Stock→Production,
  активно в 2/3-step warehouses) match-ваше swap-натите endpoints (raw
  Stock→Production) в `_adjust_procure_method` и flip-ваше raw moves на
  MTO. Последвалата MTO chain decompose-ваше Stock→Production през
  `pbm_route_id` rules и раждаше Pick picking.
- Override на `stock.move._adjust_procure_method`: за raw moves чий MO е в
  intermediate stage force `procure_method='make_to_stock'` и skip super.
  Това прекъсва MTO chain преди да тръгне.
- `_get_move_raw_values` сега също сетне `procure_method='make_to_stock'`
  в intermediate stage — defensive coverage за код пътища, които не минават
  през `action_confirm` (например manually-added raw lines).

### Changed

- `_action_prepare_production_one`: stage flip-ва на 'prepared' ПРЕДИ
  re-confirm-а на moves. Така `_adjust_procure_method` ще работи нативно
  при re-confirm. Допълнително force `procure_method='make_to_order'` на
  swap-нати raw moves преди `_action_confirm(merge=False)` — за да се
  задейства MTO chain нативно и Pick picking да се роди.

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
