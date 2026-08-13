# Copyright 2025-2026 Rosen Vladimirov, Terraros Commerce Ltd.
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.

{
    "name": "Stock Move Forced Lot Multi",
    "summary": "Force multiple lots on stock moves from MO to PO",
    "version": "19.0.1.0.2",
    "category": "Warehouse Management",
    "website": "https://github.com/rosenvladimirov/manufacture",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd., Odoo Community Association (OCA)",
    "maintainers": ["rosen-vladimirov"],
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
