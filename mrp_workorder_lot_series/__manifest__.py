# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Workorder Lot Series',
    'summary': """
        Add possibili to make seies by SN in workorder""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'barcode_mrp_workorder',
        'mrp_bom_losses',
        'product_external_reference',
        'queue_job',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mrp_work_order_data.xml',
        'views/product_template_views.xml',
        'views/mrp_workorder_views.xml',
        'wizard/mrp_workorder_series.xml',
    ],
    'demo': [
    ],
}
