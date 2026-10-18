# Changelog

## 19.0.1.2.0 (2026-10-18)

### Changed
- Port to Odoo 19, functionally equal to 18.0.1.2.0.
- `uom.category` no longer exists: UoM compatibility is checked with
  `uom.uom._has_common_reference()` (shared reference unit) instead of
  comparing `category_id`. In 19 `_compute_quantity` does not raise on
  incompatible units, so the check is done before every conversion.
- Square meter is looked up by the 19 XML ID `uom.product_uom_square_meter`
  (18: `uom.uom_square_meter`, kept as fallback).
- `purchase.order.line.product_uom` -> `product_uom_id`.
- Lot form: `product_uom_qty` is placed after the on-hand quantity row
  (19 wraps `product_qty` in an unlabeled div inside `inventory_group`).
- `_po_split_total_area` returns `None` when `stock.lot.po_split` is not
  available (provided by `stock_move_forced_lot_multi`).

### Added
- Tests for pieces calculation (m², m, related and unrelated UoM) and the
  `po_split` total area helper.

## 18.0.1.2.0

- `po_split` lots: PO line quantity is SET to the lot total area (new line
  and update of an existing line) instead of being accumulated.

## 18.0.1.1.0 (2026-04-14)

### Changed
- Move `width / height / thickness` out of the main two-column group into a
  dedicated single-column group `dimension_group` (string "Dimensions"),
  rendered after `main_group`. Prevents visual duplication next to Property
  fields that carry similar labels ("Leaf Width (mm)" etc.).

## 18.0.1.0.0

- Initial release: dimensions (width/height/thickness) and pieces calculation
  for PO lines using forced lots.
