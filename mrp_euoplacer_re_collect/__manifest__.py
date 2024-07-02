# Copyright 2023 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Euoplacer Re Collect',
    'summary': """
        Wizard for re collector for europlce files""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'europlacer_fs',
        'mrp',
        'product_label_prefix',
    ],
    'data': [
        'wizard/mrp_production_europlacer.xml',
    ],
    'demo': [
    ],
}
