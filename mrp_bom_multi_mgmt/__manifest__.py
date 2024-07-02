# Copyright 2022 Rosen Vladimirov, BioPrint Ltd.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Mrp Bom Multi Mgmt',
    'summary': """
        Wizard for adding materials in BOM""",
    'version': '11.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Rosen Vladimirov, BioPrint Ltd.,Odoo Community Association (OCA)',
    'website': 'https://github.com/rosenvladimirov/manufacture',
    'depends': [
        'product',
        'mrp',
        'web_widget_x2many_2d_matrix',
        'sale_order_variant_mgmt',
    ],
    'data': [
        'data/product_attribute.xml',
        'data/product_attribute_value.xml',
        'wizards/bom_manage_variant_view.xml',
        'views/mrp_bom_view.xml',
    ],
    'demo': [
    ],
}
