# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Stock Move Forced Lot Multi",
    "summary": "Force multiple lots on stock moves from MO to PO",
    "version": "19.0.1.0.1",
    "category": "Warehouse Management",
    "website": "https://github.com/OCA/stock-logistics-workflow",
    "author": "Your Company, Odoo Community Association (OCA)",
    "maintainers": [],
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "stock",
        "purchase_stock",
        "mrp",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_move_views.xml",
        "views/stock_move_forced_lot_wizard_views.xml",
        "views/purchase_order_views.xml",
        "views/mrp_production_views.xml",
    ],
}
