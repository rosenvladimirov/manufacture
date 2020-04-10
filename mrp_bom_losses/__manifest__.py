# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    "name": "Losses in Bill of Materials",
    "version": "11.0.1.0.0",
    "author": "Rosen Vladimirov",
    "website": "",
    "category": "Tools",
    "depends": [
        "mrp",
        #"mrp_workcenter_costing",
    ],
    "data": [
        'wizard/workorder_add_component_lot.xml',
        'views/account_move_line_view.xml',
        "views/mrp_bom_view.xml",
        'views/mrp_routing_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_workorder_views.xml',
        'views/mrp_workcenter_view.xml',
        'report/mrp_report_views_main.xml',
        'views/mrp_unbuild_views.xml',
        #'report/mrp_bom_structure_report_templates.xml',
        #'report/mrp_bom_cost_report_templates.xml',
    ],
    'installable': True
}
