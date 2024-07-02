# Copyright 2022 Rosen Vladimirov, BioPprint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Bom Stock Move Location',
    'summary': """
        Create a stock picking from BOM""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPprint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'stock',
        'mrp',
        'barcode_mrp_workorder',
        'mrp_bom_multi',
    ],
    'data': [
        'wizard/stock_move_location.xml',
        'views/product_views.xml',
    ],
    'demo': [
    ],
}
