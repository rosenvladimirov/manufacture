# Stock Move Forced Lot Multi

## Overview

This module allows forcing multiple lots on stock moves, propagating them from Manufacturing Orders (MO) through procurement to Purchase Orders (PO).

## Use Case / Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│ MO (Manufacturing Order)                                         │
│   └── stock.move (raw material)                                  │
│           └── forced_lot_ids = [LOT001, LOT002, LOT003]  (M2M)  │
└─────────────────────────────────────────────────────────────────┘
                              ↓ procurement (MTO)
┌─────────────────────────────────────────────────────────────────┐
│ PO (Purchase Order)                                              │
│   └── purchase.order.line                                        │
│           ├── forced_lot_ids = [LOT001, LOT002, LOT003]  (M2M)  │
│           └── name = "Product\n\nLots:\nLOT001\nLOT002\nLOT003" │
└─────────────────────────────────────────────────────────────────┘
                              ↓ confirm PO
┌─────────────────────────────────────────────────────────────────┐
│ Picking (incoming)                                               │
│   └── stock.move                                                 │
│           ├── forced_lot_ids = [LOT001, LOT002, LOT003]         │
│           └── stock.move.line (auto-created on assign)          │
│                   ├── lot_id = LOT001                           │
│                   ├── lot_id = LOT002                           │
│                   └── lot_id = LOT003                           │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Many2many lots on stock.move**: Add multiple forced lots to any stock move
- **Procurement propagation**: Lots are passed through procurement to generated PO lines
- **PO line description**: Lot names/refs are automatically added to the PO line description
- **Automatic move.line creation**: When assigning incoming picks, move lines are auto-created per lot
- **MO integration**: Select forced lots directly on MO raw material lines
- **Merge prevention**: Moves with different forced lots are not merged

## Configuration

No special configuration needed. Install the module and you're ready to go.

## Usage

### On Manufacturing Order:

1. Create a Manufacturing Order
2. In the Components tab, find the raw material move
3. Add lots in the "Forced Lots" field (you can create new lots here)
4. Confirm the MO
5. If the product has MTO route → Purchase Order will be created with the lots

### On Purchase Order:

1. The forced lots appear on the PO line
2. The line description includes lot names
3. Confirming PO creates picking with forced lots
4. On "Check Availability", move lines are created per lot

## Technical Details

### Models Extended

- `stock.move`: `forced_lot_ids` (Many2many), `forced_lot_extra_data` (Json)
- `stock.lot`: `force_split`, `split_buffer_qty`, `po_split`
- `purchase.order.line`: `forced_lot_ids` (Many2many)
- `stock.rule`: per-lot procurement split in `run()`, merge key, PO line update
- `stock.warehouse.orderpoint`: lot sub-rules (`parent_id`, `child_ids`, `lot_id`)
- `mrp.bom.line`: `default_forced_lot_id`
- `mrp.production`: computed `forced_lot_ids`, default lot from BoM line

### Key Methods

- `stock.move._prepare_procurement_values()`: passes lots to procurement
- `stock.rule.run()` / `_split_forced_lot_procurements()`: splits `force_split` / `po_split` lots into own procurements
- `purchase.order.line._prepare_purchase_order_line_from_procurement()`: passes lots to the PO line
- `purchase.order.line._find_candidate()`: no cross-lot merge for `po_split` lots
- `purchase.order.line._prepare_stock_move_vals()`: passes lots to the incoming move
- `stock.move._forced_lot_fill_empty_lines()`: fills `lot_id` on empty move lines (after assign and before done)

## Dependencies

- `stock`
- `purchase_stock`
- `mrp`

## License

AGPL-3.0-or-later, или търговски лиценз от Rosen Vladimirov
(двоен лиценз — виж `LICENSE-COMMERCIAL.md`).

## Author

Rosen Vladimirov, Terraros Commerce Ltd.
