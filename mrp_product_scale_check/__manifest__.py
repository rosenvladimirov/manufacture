# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Product Scale Check',
    'summary': """
        Add scale control on worker order""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'depends': [
        'mrp',
        'product_scale_check',
        'barcode_mrp_workorder',
        'stock_product_scale_check',
    ],
    'data': [
        'views/mrp_workorder_views.xml',
    ],
    'demo': [
    ],
}
