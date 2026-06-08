# Copyright 2026 Rosen Vladimirov
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "MRP Production Staged Preparation",
    "summary": (
        "Inject a 'Preparation' gate after Plan. Hybrid deferral: lot-tracked "
        "(glass/bars) keep their PO/MTO chain at confirm, while non-lot-tracked "
        "internal component picks are deferred until 'Prepare for Production' "
        "releases the MO to the floor."
    ),
    "version": "18.0.2.3.0",
    "category": "Manufacturing",
    "website": "https://github.com/rosenvladimirov/manufacture",
    "author": "Rosen Vladimirov",
    "maintainers": ["rosen-vladimirov"],
    "license": "LGPL-3",
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
