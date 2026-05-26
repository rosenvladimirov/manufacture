# Changelog

## 18.0.4.1.0 (2026-05-14)

### Fixed
- `_action_assign` no longer creates duplicate zero-qty `stock.move.line`
  rows when another flow (LogiKal importer, standard reservation) has
  already seeded move_lines for the forced lots. Skips lots that already
  appear on the move; splits the empty reservation line only among the
  remaining lots.

### Notes
- Complements the LogiKal importer fix in
  `project_management_logikal` v8.0.23 which syncs `move.product_uom_qty`
  to `sum(round(lot.product_uom_qty, uom.rounding))` so declared demand
  matches what the per-lot reservation can physically achieve (no more
  0.01 m² mismatch between заявено and консумирано).

## 18.0.4.0.0 (2026-05-13)

### Changed (breaking)
- **Per-lot orderpoint is now a parent-child structure on
  `stock.warehouse.orderpoint` itself**, not extra fields on `stock.lot`.
  A lot-level rule is a *child* orderpoint with its own
  `product_min_qty`/`product_max_qty` and a `lot_id`. Children inherit
  product / location / warehouse / company / route from parent at create
  time. Max depth is 2 (parent → child only).
- The cron scheduler picks up children automatically — no custom
  scheduler. Each child fires its own procurement with
  `forced_lot_ids = [child.lot_id]`.
- Parent's `_get_qty_to_order` returns 0 when it has children — children
  carry the policy, parent never double-orders. Lots arriving as
  `forced_lot_ids` from other flows (MTO / manual) and not registered as
  children still fall through the parent's product-level rule.

### Added
- `parent_id` / `child_ids` on `stock.warehouse.orderpoint` (self-referential).
- `lot_id` on `stock.warehouse.orderpoint` — set only on children; the
  procurement they emit is locked to this single lot.
- `is_lot_child` computed boolean (stored, indexed) — used by the default
  search domain to hide children from the standard Replenishment Report.
- `allowed_lot_ids` computed M2M + `_get_lot_domain()` placeholder hook.
  Dependent modules override `_get_lot_domain` to inject extra filters
  (supplier, attribute, production date, etc.) — the M2O picker on
  sub-rules reads from `allowed_lot_ids` rather than a hardcoded domain.
- `lot_id` field uses `ondelete="cascade"`: deleting a lot removes its
  sub-rule automatically.
- Form view: notebook tab "Lot Sub-rules" on parent orderpoints with an
  inline editable list of children.
- List view: default order `parent_id, id`; default action domain
  `[('is_lot_child', '=', False)]` hides children. Search filters
  "Lot Sub-rules" / "Parents only" available.

### Removed
- `stock.lot.lot_min_qty`, `stock.lot.lot_max_qty` — replaced by
  `product_min_qty`/`product_max_qty` on the child orderpoint itself
  (the standard fields). Migration drops the columns.
- `stock.lot._get_on_hand_qty`, `_get_qty_in_progress`,
  `_get_replenish_need` helpers — no longer needed; standard orderpoint
  qty computation handles the lot scope via `_get_product_context`
  injection of `lot_id`.
- M2M `stock.warehouse.orderpoint.lot_ids` (relation table
  `stock_orderpoint_lot_rel`) — superseded by `child_ids`.
- `procurement_group._get_split_qty_for_lot` lost the lot_min_qty branch
  (priority 0). The split path is back to force_split / po_split only —
  children-emitted procurements carry exactly one forced_lot and require
  no carve-out.

### Migration (18.0.3.0.0 → 18.0.4.0.0)
- `migrations/18.0.4.0.0/post-migrate.py` converts any v18.0.3.0.0
  configuration into the new structure: for each (orderpoint, lot) pair
  in `stock_orderpoint_lot_rel` where the lot had `lot_min_qty > 0`,
  creates a child orderpoint copying `lot_min_qty`/`lot_max_qty` into
  `product_min_qty`/`product_max_qty`. Then drops the relation table
  and the obsolete columns.

## 18.0.3.0.0 (2026-05-13)

### Added
- Per-lot orderpoint replenishment. Two new fields on `stock.lot`:
  - `lot_min_qty` — reorder trigger (when on-hand + in-progress for this
    lot at the orderpoint location drops below this, the lot is queued
    for replenishment).
  - `lot_max_qty` — target. The orderpoint orders enough to bring the
    lot up to this quantity.
- New M2M `stock.warehouse.orderpoint.lot_ids` — explicit list of lots
  this orderpoint monitors. Only listed lots are checked against
  `lot_min_qty`/`lot_max_qty`; all other lots of the same product are
  ignored. Empty list = product-level orderpoint only (no per-lot
  trigger).
- Notebook page "Tracked Lots" on the orderpoint form with inline
  editable list (lot name, min, max, force_split, po_split). Domain
  enforces same product as the orderpoint; switching the product clears
  inconsistent lots via onchange.
- `stock.lot._get_on_hand_qty(location)`, `_get_qty_in_progress(location)`,
  `_get_replenish_need(location)` helpers. `in_progress` sums pending
  incoming moves with `forced_lot_ids` containing the lot, so daily
  scheduler runs do not generate duplicate POs while a previous one is
  still open.
- `stock.warehouse.orderpoint._get_qty_to_order` override stretches the
  total qty to `max(super_qty, Σ lot_replenish_need)` so the per-lot split
  downstream has enough parent qty to carve out.
- `_get_replenish_lots()` merges pending-move forced lots with the
  orderpoint's `lot_ids` that triggered their `lot_min_qty`. Used by
  `_prepare_procurement_values` in place of the old `_get_forced_lots`.

### Changed
- `procurement_group._get_split_qty_for_lot` gains a new priority-0
  branch: lots with `lot_min_qty > 0` and `lot_max_qty > 0` use
  `_get_replenish_need(procurement.location_id)` as their split qty,
  overriding `force_split` / `po_split` for that lot. Lots without
  per-lot min/max keep the existing behavior.
- `_split_forced_lot_procurements` now treats a lot with active min/max
  trigger as a "separate" lot (its own procurement) regardless of
  `force_split` / `po_split` flags.

### Notes
- `lot_max_qty` is required (in form view) only when `lot_min_qty > 0`.
- On-hand uses `child_of` the orderpoint's location — matches standard
  Odoo orderpoint scope.

## 18.0.2.4.0 (2026-04-24)

### Changed
- `_split_forced_lot_procurements` now also splits lots flagged `po_split`
  (in addition to `force_split`). A `po_split` lot gets its own procurement
  with qty = `parent_qty / po_split_count` (even distribution across all
  po_split lots on that procurement). This guarantees one PO line per
  (product, lot) — previously a procurement carrying multiple shared glass
  lots `[X, Y, Z]` produced a single PO line with three lots.
- `_get_split_qty_for_lot` extracted as the single source of truth for
  per-lot qty: prefers `split_buffer_qty` when `force_split` is set, falls
  back to parent-qty / po_split_count when only `po_split` is set.

## 18.0.2.3.0 (2026-04-15)

### Fixed
- `_split_forced_lot_procurements` вече намалява parent procurement qty с
  сумата на split-натите `split_buffer_qty`. Ако всички lot-ове покриват
  пълния qty, parent procurement се drop-ва изцяло (не се append-ва).
  Това премахва "master дубъл" move в picking-а (където преди оставаше
  неразпределен move с пълния оригинален qty паралелно на split-натите
  child moves).

## 18.0.2.2.0 (2026-04-14)

### Changed (breaking)
- Renamed `stock.lot.force_separate_mo` → `stock.lot.force_split`. The flag
  is procurement-agnostic (MO, PO, any flow), so the `_mo` suffix was
  misleading. Labels and search filter updated accordingly.

## 18.0.2.1.0 (2026-04-14)

### Added
- Restored `stock.lot.force_separate_mo` boolean as the explicit gate for
  split. A forced lot is split into its own MO/PO **only** when
  `force_separate_mo = True` AND `split_buffer_qty > 0`.
- `split_buffer_qty` is rendered visible/required only while
  `force_separate_mo = True` in the lot form.
- Search filter "Split Into Separate Procurement" on stock.lot.

### Changed
- `procurement_group._split_forced_lot_procurements` now keeps non-flagged
  forced lots attached to the parent procurement (parent qty preserved),
  and spawns one extra procurement per flagged lot sized by its
  `split_buffer_qty`.

## 18.0.2.0.0 (2026-04-14)

### Changed (breaking)
- Removed all quantity-manipulation logic. The module no longer touches
  `stock.lot.quantity`, no longer redistributes `stock.move.line.quantity`
  for incoming moves, and no longer splits parent procurement qty by lot
  count. Receipt-time lot quantities stay informational / user-driven.
- Global per-lot split on `procurement.group.run`: any procurement carrying
  `forced_lot_ids` is expanded into one procurement per lot, regardless of
  flow (MTO, orderpoint, manual). Applies uniformly to MO and PO paths.

### Added
- New `stock.lot.split_buffer_qty` (Float, Product UoM digits). Used as the
  requested quantity when a per-lot procurement / MO / PO is generated from
  a forced lot. Lots with `split_buffer_qty <= 0` are skipped with a warning.

### Removed
- `stock.lot.force_separate_mo` field and related views / filter — split is
  now global.
- `stock.move._action_assign` override, `_create_forced_lot_move_lines`,
  `_get_qty_per_lot`, `_merge_moves` override (distinct_fields is enough).
- Orderpoint `_get_forced_lot_demand` with grouped/separate qty arithmetic,
  replaced by simple `_get_forced_lots` collector.
- `procurement_group._split_procurement_by_separate_lots` and the
  `forced_lot_demand` / `remaining_qty` branches.

## 18.0.1.1.0 (2026-04-13)

### Added
- New field `force_separate_mo` on `stock.lot`. When a forced lot carries this
  flag and appears in a procurement triggered from MTO or orderpoint, the
  procurement is split so the flagged lot produces its own dedicated MO/PO
  instead of being grouped with other forced lots.
- Form / tree / search view inheritance for `stock.lot` exposing the new flag.
- `procurement.group._split_procurement_by_separate_lots` helper handling the
  MTO path (procurements arriving with direct `forced_lot_ids`).
- `stock.warehouse.orderpoint._get_forced_lot_demand` now isolates flagged
  lots in the demand dictionary so each one becomes its own procurement.

## 18.0.1.0.0

- Initial release: force multiple lots on stock moves from MO to PO.
