# Copyright 2021 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Stock Move Location',
    'summary': """
        Collect and create picking form MO for stock move between productions and warehouse without orderpoint manual.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'mrp',
        'stock',
        'sale',
        'sale_stock',
        'barcode_mrp_workorder',
        'mrp_bom_multi',
        'stock_quant_manual_assign_mrp',
        'l10n_bg_extend_locations',
        'block_putaway_strategy',
    ],
    'data': [
        'wizard/stock_move_location.xml',
        'views/mrp_production_views.xml',
        'views/stock_picking_views.xml',
    ],
    'demo': [
    ],
}
