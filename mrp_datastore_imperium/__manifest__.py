# Copyright 2021 Rosen Vladimirov, Toma Tomov
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Datastore Imperium',
    'summary': """
        Import from Imperium product consumtion""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, Toma Tomov,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'barcodes',
        'mrp_bom_losses'
    ],
    'data': [
        'wizard/mrp_import_imperium.xml',
        'views/res_config_settings.xml',
        'views/mrp_workorder_views.xml',
        'views/mrp_bom_view.xml',
    ],
    'demo': [
    ],
}
