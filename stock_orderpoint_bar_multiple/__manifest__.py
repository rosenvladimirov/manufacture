# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html
{
    "name": "Stock Orderpoint Bar Multiple",
    "summary": (
        "Seed the reordering multiple of bar-like materials from the standard "
        "bar length, once, when the orderpoint is created. A purchase packaging "
        "(bundle) or a manual entry overrides the seed and stays locked. "
        "Offcut lots are never used as a source."
    ),
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "website": "https://github.com/rosenvladimirov/manufacture-experts",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "maintainers": ["rosen-vladimirov"],
    "license": "OPL-1",
    "application": False,
    "installable": True,
    "depends": [
        "stock",
        "purchase_stock",
    ],
    "data": [
        "views/stock_warehouse_orderpoint_views.xml",
    ],
}
