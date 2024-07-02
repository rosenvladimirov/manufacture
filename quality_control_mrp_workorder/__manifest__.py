# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2014 Oihane Crucelaegui - AvanzOSC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "MRP extension on work order for quality control",
    "version": "11.0.1.0.0",
    "category": "Quality control",
    "license": "AGPL-3",
    "author": "Rosen Vladimirov, "
              "BoPrint Ltd., "
              "OdooMRP team, "
              "AvanzOSC, "
              "Serv. Tecnol. Avanzados - Pedro M. Baeza, "
              "Agile Business Group, "
              "Odoo Community Association (OCA)",
    "website": "https://github.com/rosenvladimirov/manufacture/tree/11.0/"
               "quality_control_mrp_workorder",
    "depends": [
        "quality_control",
        "quality_control_stock",
        "quality_control_mrp",
        "quality_control_plan",
        "mrp",
    ],
    "data": [
        'data/quality_control_mrp_workorder_data.xml',
        'views/mrp_workorder_view.xml',
        'views/qc_inspection_view.xml',
        'views/qc_test_view.xml',
    ],
    "installable": True,
    "auto_install": False,
}
