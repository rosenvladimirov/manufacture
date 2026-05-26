# Changelog

## 18.0.1.1.0 (2026-04-14)

### Changed
- Move `width / height / thickness` out of the main two-column group into a
  dedicated single-column group `dimension_group` (string "Dimensions"),
  rendered after `main_group`. Prevents visual duplication next to Property
  fields that carry similar labels ("Leaf Width (mm)" etc.).

## 18.0.1.0.0

- Initial release: dimensions (width/height/thickness) and pieces calculation
  for PO lines using forced lots.
