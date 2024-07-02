# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Stock Location',
    'summary': """
        Added field in stock move line for raw materials source location and final product destination location.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'stock',
        'mrp',
    ],
    'data': [
        'views/stock_move_line_views.xml',
    ],
    'demo': [
    ],
}
