# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Stock Forecast MTO Chain Fix",
    "summary": "Derive forecast (qty, date) for MTO moves from their "
               "move_orig_ids chain instead of the non-deterministic global "
               "forecast report allocation. Fixes the MO forecast_widget "
               "flicker on identical reserved components and unmasks "
               "unreserved ones. Warehouse-scoped; MTO-only guard avoids the "
               "v3 'available from stock' regression.",
    "version": "18.0.4.0.0",
    "category": "Warehouse Management",
    "website": "https://github.com/OCA/stock-logistics-workflow",
    "author": "Your Company",
    "license": "AGPL-3",
    "depends": ["stock"],
    "application": False,
    "installable": True,
    "auto_install": False,
}
