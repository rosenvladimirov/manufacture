# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Workorder Bufering',
    'summary': """
        Add buffer for final product and conponets to possible to record production after finish registration on all.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'barcode_mrp_workorder',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_workorder_views.xml',
    ],
    'demo': [
    ],
}
