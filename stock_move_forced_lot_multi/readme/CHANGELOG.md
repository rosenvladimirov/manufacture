# CHANGELOG

## 19.0.1.0.2 (2026-04-14)

### Fixed

- Премахнато дублирано наследяване на `stock.move` в два файла
  (`stock_move.py` и `mrp_production.py`). Всички override-и на `stock.move`
  вече са консолидирани в `stock_move.py`.
- Заменен ръчният `_merge_moves` override с правилния hook
  `_prepare_merge_moves_distinct_fields`. Това гарантира, че move-ове с
  различни forced lots няма да бъдат обединявани, следвайки стандартния
  механизъм на Odoo.

### Removed

- Премахнати празни override-и, които само извикваха `super()` без да
  добавят логика (чист мъртъв код):
  - `StockMove._get_new_picking_values`
  - `StockMove._prepare_move_line_vals`
  - `MrpProduction.action_confirm`
  - `StockMoveMrp._action_confirm`
  - `StockMoveMrp._prepare_procurement_group_vals`
  - `StockMoveMrp._compute_display_name` (със закоментиран код)
  - `StockRule._run_buy`
  - `PurchaseOrder._prepare_picking`
- Премахнат класът `MrpBomLine`, който съдържаше само закоментирано
  незавършено поле `default_forced_lot_ids`.

## 19.0.1.0.1

- Initial release.
