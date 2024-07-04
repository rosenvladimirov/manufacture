# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Workorder Auto Generate',
    'summary': """
        Add wizard for auto generate base on other WO inside manufacture order.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'stock',
        'mrp_bom_losses',
        'barcode_mrp_workorder',
        'mec_mrp'
    ],
    'data': [
        'wizard/mrp_workorder_auto.xml'
    ],
    'demo': [
    ],
}
