# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Sale Stock Move Location',
    'summary': """
        Create picking for move from base warehouse to manufacture base on selling products hu is produce in company.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'sale',
        'stock',
        'mrp',
        'barcode_mrp_workorder',
        'mrp_bom_multi',
        'project_mrp',
        'purchase_analytic_global',
    ],
    'data': [
        'wizard/stock_move_location.xml',
    ],
    'demo': [
    ],
}
