# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Product Sequence',
    'summary': """
        Add individual sequence for final product.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'conflicts': [
        'product_lot_sequence',
    ],
    'depends': [
        'product',
        'mrp_bom_losses',
        'barcode_mrp_workorder',
    ],
    'data': [
        'views/product_views.xml',
        'views/mrp_workorder_views.xml',
    ],
    'demo': [
    ],
}
