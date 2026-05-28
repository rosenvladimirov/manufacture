# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "MRP Production Staged Preparation",
    "summary": (
        "Inject a 'Preparation' gate after Plan: workorders are scheduled "
        "normally, Pick/Store pickings and PO chain are born at confirm, but "
        "the MO sits in 'Preparation' state until the operator clicks "
        "'Prepare for Production' to release it to the floor."
    ),
    "version": "18.0.2.1.0",
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
