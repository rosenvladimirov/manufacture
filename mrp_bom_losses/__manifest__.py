# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "Losses in Bill of Materials",
    "version": "11.0.1.0.0",
    "author": "Rosen Vladimirov",
    "website": "",
    "category": "Tools",
    "depends": [
        "mrp",
        "barcode_mrp_workorder",
        "mrp_production_service",
        "queue_job",
        "product",
        'subcontracted_service',
        'account_recalculate_stock_move',
        #"mrp_workcenter_costing",
    ],
    "data": [
        'data/queue_data.xml',
        # 'wizard/workorder_add_component_lot.xml',
        'views/account_move_line_view.xml',
        "views/mrp_bom_view.xml",
        "views/product_views.xml",
        "views/stock_account_views.xml",
        # 'views/mrp_routing_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_workorder_views.xml',
        'views/mrp_workcenter_view.xml',
        'report/mrp_report_views_main.xml',
        'views/mrp_unbuild_views.xml',
        'wizard/generate_sub_levels.xml',
        'wizard/change_production_qty_views.xml',
        #'report/mrp_bom_structure_report_templates.xml',
        #'report/mrp_bom_cost_report_templates.xml',
    ],
    'installable': True
}
