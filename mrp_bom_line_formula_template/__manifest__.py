{
    "name": "MRP BoM Line formula templates",
    "summary": "Manage templates for BoM line quantity formulas.",
    "version": "19.0.1.0.0",
    "author": "Rosen Vladimirov, Odoo Community Association (OCA)",
    "category": "Manufacturing",
    "depends": [
        "mrp",
        "mrp_bom_line_formula_quantity",
    ],
    "website": "https://github.com/rosenvladimirov/manufacture",
    "license": "AGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "views/mrp_bom_line_formula_template_views.xml",
    ],
    "installable": True,
    "application": False,
}
