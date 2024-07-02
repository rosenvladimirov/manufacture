# Copyright 2014 Serv. Tec. Avanzados - Pedro M. Baeza
# Copyright 2014 Oihane Crucelaegui - AvanzOSC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Color kanban quality control",
    "version": "11.0.1.0.0",
    "category": "Quality control",
    "license": "AGPL-3",
    "author": "Rosen Vladimirov, "
              "BioPrint Ltd. , "
              "Odoo Community Association (OCA)",
    "website": "https://github.com/rosenvladimirov/manufacture/tree/11.0/"
               "quality_control_kanban",
    "depends": [
        "quality_control",
    ],
    "data": [
        "views/qc_inspection_view.xml",
    ],
    "installable": True,
    "auto_install": True,
}
