# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp External Docs',
    'summary': """
        Add links for external documentation in route operation.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'base',
        'mail',
        'mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/ir_attachment_view.xml',
        'views/techical_documents_type_views.xml',
        'views/mrp_routing_view.xml',
        'views/mrp_workorder_views.xml',
    ],
    'demo': [
    ],
}
