# -*- coding: utf-8 -*-
{
    'name': 'MRP BOM Line Type Override',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Override BOM type from BOM line configuration',
    'description': """
        Allows setting BOM type (Normal/Kit) at the BOM line level.
        The line type overrides the child BOM type during explosion.
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'AGPL-3',
    'depends': ['mrp'],
    'data': [
        'views/mrp_bom_line_views.xml',
    ],
    'post_load': 'post_load',
    'installable': True,
    'application': False,
    'auto_install': False,
}
