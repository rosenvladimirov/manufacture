# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name" : "ALfresco worksheet add in MRP",
    "version" : "11.0.1.0",
    "author" : "Rosen Vladimirov",
    'category': 'Manufacturing',
    "description": """
Integrations alfresco CMIS in MRP
    """,
    'depends': [
        'mrp',
        'cmis_field',
    ],
    "demo" : [],
    "data" : [
            'views/mrp_routing_views.xml',
    ],
    'license': 'AGPL-3',
    "installable": True,
}
