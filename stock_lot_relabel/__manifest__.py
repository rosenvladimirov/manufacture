# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html
{
    "name": "Stock Lot Relabel",
    "summary": (
        "Change the lot of stock in place through a virtual 'Lot Relabel' "
        "location: one move out with the source lot, one move back in with "
        "the target lot, equal value, posted on configurable accounts."
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
        "stock_account",
    ],
    "post_init_hook": "post_init_hook",
}
