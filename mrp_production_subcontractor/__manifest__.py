# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Production Subcontractor',
    'summary': """
        Manage production by subcontractors.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'account',
        'account_recalculate_stock_move',
        'stock',
        'mrp',
        'mrp_bom_losses',
        'account',
        'purchase',
        'mrp_split_production',
        'base_comment_template',
    ],
    'data': [
        'data/ir_sequence_data.xml',
        'security/ir.model.access.csv',
        "views/mrp_production_subcontractor.xml",
        "views/mrp_production_views.xml",
    ],
    'demo': [
    ],
}
