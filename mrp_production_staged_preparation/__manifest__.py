# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "MRP Production Staged Preparation",
    "summary": (
        "Two-stage MO lifecycle: confirm в 'intermediate' (forecast active, "
        "no logistic pickings) → user action 'Prepare for production' → "
        "endpoints се swap-ват към буферните локации, native procurement "
        "ражда Pick/Store pickings."
    ),
    "version": "18.0.1.0.0",
    "category": "Manufacturing",
    "website": "https://github.com/OCA/manufacture",
    "author": "BL Consulting, Odoo Community Association (OCA)",
    "maintainers": ["rosen-vladimirov"],
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "mrp",
        "stock",
    ],
    "data": [
        "views/stock_picking_type_views.xml",
        "views/mrp_production_views.xml",
    ],
}
