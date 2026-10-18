# CHANGELOG

## 19.0.4.3.2 (2026-10-18)

Довършва порта до прода на 18: пренесен е №118 от прода (18.0.4.2.2, клон
`fix/no118b-manual-po-line`), който липсваше в 19.0.4.3.1.

### Added (№118 от прода)

- `purchase.order.line._forced_lot_note_missing`: прът по лот (продукт с
  лот с `bar_length_mm` > 0 — полето е на плъгина за разкроя; без него
  проверката мълчи), който влиза в покупка от правилото за попълване БЕЗ
  форсиран лот, оставя бележка в покупката с кода на продукта. Една
  бележка за продукт на поръчка. Повод: fulltest 01.10, покупка 1741 за
  ETE E 41103 — 7 от 7 сурови движения на МО без лот, приемането спря.
- `purchase.order.button_confirm`: при потвърждаване се казват и ръчните
  редове за прът без форсиран лот (№118 т.2, fulltest 02.10, P00208);
  бележка, писана вече от правилото, не се повтаря.
- Тестове `tests/test_bar_po_without_lot.py` (8) — пропускат се, ако
  `bar_length_mm` не е инсталирано. Нов преводим низ в `.pot` и `bg.po`.

### Changed (19)

- Бележката се превежда през `self.env._` (вместо глобалното `_`).

## 19.0.4.3.1 (2026-10-18)

Порт на 18.0.4.3.1 върху 19 — версията от git репото (`rv/_other`), НЕ
кодът на прода. Продът на 18 е 18.0.4.2.2 (`data_dir`, клон
`fix/no118b-manual-po-line`): 18.0.4.3.1 е пред него с
`_forced_lot_fill_empty_lines` и по пътя на `_action_done` (решено: остава),
но е без №118 — той е пренесен в 19.0.4.3.2. Запазени са
19-специфичните поправки от 19.0.1.0.1/19.0.1.0.2 (`move_ids` вместо
`move_ids_without_package`, консолидираното наследяване на `stock.move`,
`_prepare_merge_moves_distinct_fields`).

### Added (от 18.0.2.x – 18.0.4.3.1)

- `stock.lot.force_split`, `split_buffer_qty`, `po_split` + изгледи и филтри.
- Разцепване на набавяне по лот (`force_split` / `po_split`) в
  `stock.rule.run` — в 18 беше в `procurement.group.run`; в 19 моделът
  `procurement.group` е премахнат и `run()` е на `stock.rule`.
- `stock.rule._get_procurements_to_merge_groupby` (не слива набавяния с
  различни лотове), `_update_purchase_order_line` (добавя лотовете и
  описанието им към съществуващ PO ред),
  `purchase.order.line._find_candidate` (при `po_split` — само ред със
  същия набор лотове).
- Лот под-правила на `stock.warehouse.orderpoint` (`parent_id`, `child_ids`,
  `lot_id`, `is_lot_child`, `child_count`, `allowed_lot_ids`,
  `_get_lot_domain()`), ограничения, наследяване от родителя, отделен
  набор лот в набавянето, `lot_id` в продуктовия контекст, родител с деца
  не поръчва. Изгледи: под-правила в формата, филтри, скриване на децата
  от Replenishment.
- `_get_forced_lots`: търси чакащите движения и в основната наличност
  на склада (`warehouse_id.lot_stock_id`), не само в локацията на точката.
- `mrp.bom.line.default_forced_lot_id` → forced лот на raw движението при
  създаване на МО (`_get_move_raw_values`).
- `stock.move.forced_lot_extra_data` (Json).
- `_forced_lot_fill_empty_lines`: попълва `lot_id` на празните линии след
  `_action_assign` и преди `_action_done` (един лот → всички празни линии;
  няколко лота → разцепва единствената празна линия pro-rata; не пипа
  ръчно `lot_name` и вече засети лотове).
- Тестове (`tests/test_forced_lot_multi.py`) и превод `i18n/bg.po`.

### Changed (19)

- Ядреното `_product_location_check` (`models.Constraint`) е подменено с
  `CHECK (TRUE)`; частичните уникални индекси са `models.UniqueIndex` и се
  създават и при чиста инсталация (в 18 — само от миграцията 18.0.4.0.0).
- Сигнатури по 19: `_prepare_procurement_values(date=False)`,
  `_get_qty_to_order(qty_in_progress_by_orderpoint=None)`,
  `_get_product_context()`.
- `split_buffer_qty` ползва точността `Product Unit` (името в 19).
- Съобщенията на ValidationError са преводими (`self.env._`).
- `child_count` е с етикет „Lot Sub-rules Count“ (беше същият като на
  `child_ids`).
- Help на `default_forced_lot_id` е на английски.

### Removed

- `_create_forced_lot_move_lines` / `_get_qty_per_lot` и извикването им от
  съветника — премахнати в 18.0.2.0.0, заменени от
  `_forced_lot_fill_empty_lines`.
- Миграциите `migrations/18.0.4.0.0/*` не се носят: конвертират схемата на
  18.0.3.0.0, която в 19 база не съществува; индексите вече са декларирани
  в модела.

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
