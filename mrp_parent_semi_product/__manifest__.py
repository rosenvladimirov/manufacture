# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Parent Semi Product',
    'summary': """
        Add filed parent semi product in product files.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'product',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'demo': [
    ],
}
