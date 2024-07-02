# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "MRP Merge opened productions",
    "summary": "Merge many opened production order in one new and cancel merged orders",
    "author": "Rosen Vladimirov, "
              "BioPrint Ltd."
              "Odoo Community Association (OCA)",
    "website": "https://odoo-community.org/",
    "category": "Manufacturing",
    "version": "11.0.0.1.0",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "mrp",
    ],
    "data": [
        'wizards/merge_mrp_production.xml',
    ],
    "demo": [
    ],
}
