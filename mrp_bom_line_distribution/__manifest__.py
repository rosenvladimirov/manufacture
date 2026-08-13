#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "MRP BoM Line Distribution",
    "summary": "Manage distribution coefficients on BoM lines",
    "version": "19.0.1.0.0",
    "author": "vladimirov.rosen@gmail.com",
    "category": "Manufacturing",
    "depends": [
        "mrp",
    ],
    "license": "AGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "views/mrp_bom_line_views.xml",
        "views/mrp_bom_views.xml",
        "views/mrp_production_views.xml",
        "views/distribution_log_views.xml",
        "views/report_mrp_bom_structure.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mrp_bom_line_distribution/static/src/js/mrp_bom_overview_distribution.js",
            "mrp_bom_line_distribution/static/src/xml/mrp_bom_overview_distribution.xml",
        ],
    },
}
