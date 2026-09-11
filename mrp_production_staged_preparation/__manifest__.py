# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html
{
    "name": "MRP Production Staged Preparation",
    "summary": (
        "Inject a 'Preparation' gate after Plan. Hybrid deferral: lot-tracked "
        "(glass/bars) keep their PO/MTO chain at confirm, while non-lot-tracked "
        "internal component picks are deferred until 'Prepare for Production' "
        "releases the MO to the floor."
    ),
    "version": "18.0.2.19.0",
    "category": "Manufacturing",
    "website": "https://github.com/rosenvladimirov/manufacture-experts",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "maintainers": ["rosen-vladimirov"],
    "license": "OPL-1",
    "application": False,
    "installable": True,
    "depends": [
        "mrp",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/mrp_production_prepare_wizard_views.xml",
        "wizards/mrp_production_unprepare_wizard_views.xml",
        "views/stock_picking_type_views.xml",
        "views/mrp_production_views.xml",
    ],
}
