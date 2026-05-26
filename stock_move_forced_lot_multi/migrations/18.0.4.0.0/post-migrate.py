# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Migrate v18.0.3.0.0 → v18.0.4.0.0.

Converts the M2M `stock.warehouse.orderpoint.lot_ids` + per-lot
`stock.lot.lot_min_qty`/`lot_max_qty` configuration into the new
parent-child orderpoint structure: each tracked lot becomes a child
orderpoint under its product-level parent, copying min/max into the
standard `product_min_qty`/`product_max_qty` fields.

Idempotent: skips conversion when the relation table or the legacy
columns are already gone, and avoids creating duplicate children.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Create the partial unique indexes that replace the dropped
    # `product_location_check` constraint. Done here (not pre-migrate)
    # because lot_id / parent_id columns only exist after Odoo's
    # `_auto_init` has run for the upgraded model.
    cr.execute("""
        DROP INDEX IF EXISTS stock_warehouse_orderpoint_product_location_parent_idx;
        DROP INDEX IF EXISTS stock_warehouse_orderpoint_parent_lot_idx;
    """)
    cr.execute("""
        CREATE UNIQUE INDEX stock_warehouse_orderpoint_product_location_parent_idx
            ON stock_warehouse_orderpoint
                (product_id, location_id, company_id, warehouse_id)
            WHERE lot_id IS NULL
    """)
    cr.execute("""
        CREATE UNIQUE INDEX stock_warehouse_orderpoint_parent_lot_idx
            ON stock_warehouse_orderpoint (parent_id, lot_id)
            WHERE parent_id IS NOT NULL AND lot_id IS NOT NULL
    """)
    _logger.info(
        "Created partial unique indexes: parents (product/location/"
        "company/warehouse) where lot is null, children (parent, lot)."
    )

    # Guard: skip cleanly if the legacy schema is already gone.
    cr.execute("""
        SELECT to_regclass('stock_orderpoint_lot_rel') AS rel_tbl,
               (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stock_lot' AND column_name = 'lot_min_qty') AS has_col
    """)
    rel_tbl, has_col = cr.fetchone()
    if not rel_tbl and not has_col:
        _logger.info("Nothing to migrate — legacy schema already absent.")
        return

    converted = 0
    if rel_tbl and has_col:
        cr.execute("""
            SELECT r.orderpoint_id, r.lot_id,
                   l.lot_min_qty, l.lot_max_qty,
                   op.product_id, op.location_id, op.warehouse_id,
                   op.company_id, op.route_id, op.qty_multiple,
                   op.name
            FROM stock_orderpoint_lot_rel r
            JOIN stock_lot l ON l.id = r.lot_id
            JOIN stock_warehouse_orderpoint op ON op.id = r.orderpoint_id
            WHERE COALESCE(l.lot_min_qty, 0) > 0
        """)
        rows = cr.fetchall()
        for (op_id, lot_id, min_q, max_q,
             product_id, location_id, warehouse_id,
             company_id, route_id, qty_multiple, op_name) in rows:
            # Skip if a child for this (parent, lot) already exists.
            cr.execute("""
                SELECT id FROM stock_warehouse_orderpoint
                WHERE parent_id = %s AND lot_id = %s
                LIMIT 1
            """, (op_id, lot_id))
            if cr.fetchone():
                continue

            child_name = f"{op_name} / lot {lot_id}"
            cr.execute("""
                INSERT INTO stock_warehouse_orderpoint
                    (name, parent_id, lot_id, product_id, location_id,
                     warehouse_id, company_id, route_id, qty_multiple,
                     product_min_qty, product_max_qty,
                     active, trigger, create_uid, create_date,
                     write_uid, write_date)
                VALUES
                    (%s, %s, %s, %s, %s,
                     %s, %s, %s, %s,
                     %s, %s,
                     TRUE, 'auto', 1, NOW(),
                     1, NOW())
                RETURNING id
            """, (child_name, op_id, lot_id, product_id, location_id,
                  warehouse_id, company_id, route_id, qty_multiple or 0.0,
                  min_q, max_q))
            converted += 1

        _logger.info(
            "Created %d child orderpoint(s) from legacy lot_min_qty config.",
            converted,
        )

        # Backfill `is_lot_child` for SQL-inserted rows — Odoo's stored
        # compute only fires on ORM writes, not raw INSERTs.
        cr.execute("""
            UPDATE stock_warehouse_orderpoint
            SET is_lot_child = (parent_id IS NOT NULL AND lot_id IS NOT NULL)
            WHERE is_lot_child IS DISTINCT FROM
                  (parent_id IS NOT NULL AND lot_id IS NOT NULL)
        """)

    # Drop the legacy M2M relation table — superseded by child_ids.
    if rel_tbl:
        cr.execute("DROP TABLE IF EXISTS stock_orderpoint_lot_rel CASCADE")
        _logger.info("Dropped legacy table stock_orderpoint_lot_rel.")

    # Drop the legacy stock.lot columns — fields removed from the model.
    if has_col:
        cr.execute("""
            ALTER TABLE stock_lot
                DROP COLUMN IF EXISTS lot_min_qty,
                DROP COLUMN IF EXISTS lot_max_qty
        """)
        _logger.info("Dropped stock_lot.lot_min_qty / lot_max_qty columns.")
