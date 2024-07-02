# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Alternatives',
    'summary': """
        Menage alternative materials in manufacture order and work order.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'mrp_bom_losses',
    ],
    'data': [
        'views/mrp_bom_views.xml',
        'views/product_views.xml',
        'wizards/mrp_workorder_alternatives.xml',
        'views/mrp_workorder_views.xml',
    ],
    'demo': [
    ],
}
