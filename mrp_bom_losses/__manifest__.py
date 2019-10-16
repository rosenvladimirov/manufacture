# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    "name": "Losses in Bill of Materials",
    "version": "12.0.1.0.0",
    "author": "Rosen Vladimirov, dXFactory Ltd.",
    "website": "",
    "category": "Tools",
    "depends": [
        "mrp",
        #"mrp_workcenter_costing",
    ],
    "data": [
        "views/mrp_bom_view.xml",
        'views/mrp_routing_views.xml',
        'views/product_views.xml',
        'report/mrp_report_views_main.xml',
        'report/mrp_report_bom_structure.xml',
    ],
    'installable': True
}
