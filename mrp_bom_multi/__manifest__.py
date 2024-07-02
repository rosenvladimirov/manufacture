# Copyright 2021 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Bom Multi',
    'summary': """
        Create eazy multi boms, and use for grouping by sale orders.""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'conflicts': [
        'sale_mrp_link',
        'mrp_production_grouped_by_product',
    ],
    'depends': [
        'mrp',
        'product_brand',
        'sale',
        'mrp_bom_losses',
        'web_timeline',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/semi_product_add_component.xml',
        # 'wizard/change_production_src_location.xml',
        'views/product_views.xml',
        'views/mrp_bom_view.xml',
        'views/mrp_production_views.xml',
        'wizard/generate_sub_levels.xml',
    ],
    'demo': [
    ],
}
