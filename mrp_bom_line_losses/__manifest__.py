#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "MRP BoM Line Losses",
    "summary": "Compute the quantity of a Production Line with losses",
    "version": "18.0.2.0.3",
    "author": "vladimirov.rosen@gmail.com",
    "category": "Manufacturing",
    "depends": [
        "mrp",
    ],
    "license": "AGPL-3",
    "data": [
        "views/mrp_bom_line_views.xml",
        "views/mrp_bom_views.xml",
        "views/report_mrp_bom_structure.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mrp_bom_line_losses/static/src/js/mrp_bom_overview_loss.js",
            "mrp_bom_line_losses/static/src/xml/mrp_bom_overview_loss.xml",
        ],
    },
}
