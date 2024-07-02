# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Final Product Alternative',
    'summary': """
        Search in MOMP done for final product component SN/LOT and to return produced SN/LOT""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'barcode_mrp_workorder',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_workorder_views.xml'
    ],
    'demo': [
    ],
}
