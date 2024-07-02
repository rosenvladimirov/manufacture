# © 2015 Oihane Crucelaegui - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    "name": "Notes in Bill of Materials lines",
    "version": "11.0.1.0.0",
    "license": "AGPL-3",
    "author": "OdooMRP team,"
              "AvanzOSC,"
              "Serv. Tecnol. Avanzados - Pedro M. Baeza, "
              "Odoo Community Association (OCA)",
    "website": "http://www.odoomrp.com",
    "category": "Tools",
    "depends": [
        "mrp",
        "web_widget_open_tab",
    ],
    "data": [
        "views/mrp_bom_view.xml",
        "views/mrp_production_views.xml",
        "views/product_views.xml",
    ],
    'installable': True
}
