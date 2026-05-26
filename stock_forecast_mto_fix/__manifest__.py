# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Stock Forecast MTO Chain Fix",
    "summary": "Warehouse-scoped fallback to move_orig_ids chain when the "
               "forecast report fully drops an MTO outgoing move "
               "(fake 'Not Available'). Case 2 date-fallback removed — it "
               "broke valid 'available now' semantics.",
    "version": "18.0.3.0.0",
    "category": "Warehouse Management",
    "website": "https://github.com/OCA/stock-logistics-workflow",
    "author": "Your Company",
    "license": "AGPL-3",
    "depends": ["stock"],
    "application": False,
    "installable": True,
    "auto_install": False,
}
