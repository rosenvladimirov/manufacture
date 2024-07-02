# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Split Production',
    'summary': """
        Split manufacture production.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'mrp_bom_losses',
        "product",
        'mrp_bom_multi',
        'mrp_stock_move_location',
        'mrp_workorder_auto_finish',
        'queue_job',
    ],
    'data': [
        'wizard/mrp_production_split.xml',
    ],
    'demo': [
    ],
}
