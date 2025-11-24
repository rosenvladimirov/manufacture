{
    'name': 'BOM за Лот/Сериен Номер',
    'version': '18.0.1.0.1',
    'author': 'Rosen Vladimirov, Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'license': 'AGPL-3',
    'category': 'Manufacturing',
    'summary': 'BOM management by lot/serial number with stages',
    'description': """
Lot/serial number specific BOM creation and management module.
- BOM based on the product master BOM
- Correction of quantities relative to lot/CH
- 6 named stages + 1 common stage
- Automatic loading when starting MO
    """,
    'depends': [
        'mrp',
        'stock',
        'product',
        'markdown_viewer_locale'
    ],
    'data': [
        'data/ir_sequence_data.xml',
        'security/ir.model.access.csv',
        'views/mrp_bom_lot_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_bom_views.xml',
        'views/stock_lot_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Добавяме регистрацията на документацията
            ('after', 'markdown_viewer_locale/static/src/js/markdown_registry.js',
             'mrp_bom_for_lot/static/src/js/mrp_bom_for_lot_markdown.js'),
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
