# Changelog

All notable changes to the mrp_bom_line_losses module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [18.0.2.2.0] - 2026-03-05

### Fixed
- **mrp_production.py — `_link_bom` override:**
  - Loss/efficiency factor was not applied when BOM is re-synced on a confirmed MO.
    Root cause: core's `_link_bom` directly sets `move_raw.product_uom_qty = bom_qty / ratio`
    (line 2570) for existing moves without calling `_get_move_raw_values`.
  - Fix: override `_link_bom` to apply loss factor to all `move_raw_ids` after `super()`.
    Only runs for confirmed/in-progress MOs (`state not in cancel/done/draft`), since draft
    MOs delete and recreate moves via `_get_move_raw_values` which already applies the factor.
  - Example: BOM line qty = 10, loss = 10% → `_get_move_raw_values` sets 11 on creation,
    `_link_bom` now also sets 11 on re-sync (was 10 before fix).

## [18.0.2.1.0] - 2026-03-05

### Fixed
- **JS (`mrp_bom_overview_loss.js`):** `clampPercent()` now accepts negative values down to -99%
  (was clamping to 0, blocking efficiency gains in BOM Overview UI).

### Changed
- **Field label:** `loss` field renamed from "Losses" to "Loss / Efficiency" with updated help text
  explaining both positive (scrap) and negative (efficiency gain) usage.
- **BOM Overview UI:** Column headers updated from "Loss %", "Qty w/ Loss", "Loss Cost"
  to "Loss/Eff. %", "Adj. Qty", "Adj. Cost" to reflect dual-purpose semantics.
- **PDF report:** Same header updates in `report_mrp_bom_structure.xml`.
- **Input field:** `maxlength` increased from 6 to 7 to accommodate negative values (e.g. "-99.5").

## [18.0.2.0.3] - 2026-03-04

### Added
- Initial release with loss percentage support on BOM lines.
- Positive loss adds extra consumption (scrap), negative reduces quantity (efficiency).
- BOM Overview integration with inline editing of loss percentage.
- PDF report columns for loss %, adjusted quantity, and adjusted cost.
- Constraint: loss must be > -100% (factor must stay positive).
