# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Stock Location Europlacer',
    'description': """
        Add clue between mrp stock move location and europlacer track""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.',
    'depends': [
        'mrp_stock_move_location',
        'europlacer',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_production_views.xml',
    ],
    'demo': [
    ],
}
