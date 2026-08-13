# Copyright 2026 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "MRP Account Move Line Button",
    "summary": "Smart button on manufacturing orders showing the debit/credit "
    "journal items in the standard account.move.line list view",
    "version": "18.0.1.0.0",
    "category": "Manufacturing",
    "author": "Rosen Vladimirov",
    "website": "https://github.com/OCA/manufacture",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "account_move_line_mrp_info",
    ],
    "data": [
        "views/mrp_production_views.xml",
    ],
}
