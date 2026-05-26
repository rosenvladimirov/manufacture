# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Pre-migrate v18.0.4.0.0.

Drops the core full-quadruple unique constraint on
`stock.warehouse.orderpoint` so the model upgrade can add the
`parent_id`/`lot_id` columns and we can re-establish a partial unique
rule in post-migrate (once the new columns exist).

Idempotent — safe to re-run.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        ALTER TABLE stock_warehouse_orderpoint
            DROP CONSTRAINT IF EXISTS stock_warehouse_orderpoint_product_location_check
    """)
    _logger.info("Dropped legacy unique constraint product_location_check.")

    cr.execute("""
        DELETE FROM ir_model_constraint
            WHERE name = 'stock_warehouse_orderpoint_product_location_check'
    """)
