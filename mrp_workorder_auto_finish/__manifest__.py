# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Mrp Workorder Auto Finish',
    'summary': """
        Auto finish work orders""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'mrp_stock_move_location',
        'mrp_bom_losses',
        'barcode_mrp_workorder',
        'product_label_prefix',
        'queue_job'
    ],
    'data': [
        'wizard/mrp_workorder_auto_process.xml',
        'views/mrp_production_views.xml',
    ],
    'demo': [
    ],
}
