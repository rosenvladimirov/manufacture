# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Stock Move Forced Lot Multi - Dimensions",
    "summary": "Add lot dimensions (width/height/thickness) and pieces calculation to PO lines",
    "version": "19.0.1.0.1",
    "category": "Warehouse Management",
    "website": "https://github.com/OCA/stock-logistics-workflow",
    "author": "Your Company, Odoo Community Association (OCA)",
    "maintainers": [],
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "stock_move_forced_lot_multi",
    ],
    "data": [
        "views/stock_lot_views.xml",
        "views/purchase_order_views.xml",
    ],
}
