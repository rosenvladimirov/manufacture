# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html
{
    "name": "MRP Production Staged Preparation",
    "summary": (
        "Inject a 'Preparation' gate after Plan. Hybrid deferral: lot-tracked "
        "(glass/bars) keep their PO/MTO chain at confirm, while non-lot-tracked "
        "internal component picks are deferred until 'Prepare for Production' "
        "releases the MO to the floor."
    ),
    "version": "18.0.2.32.1",
    "category": "Manufacturing",
    "website": "https://github.com/rosenvladimirov/manufacture-experts",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "maintainers": ["rosen-vladimirov"],
    "license": "OPL-1",
    "application": False,
    "assets": {
        "web.assets_backend": [
            "mrp_production_staged_preparation/static/src/js/staged_cut_ready_service.js",
        ],
    },
    "installable": True,
    "depends": [
        "mrp",
        "stock",
        # №93: смяната на лота на остатъка (6500 → 4630) — две движения през
        # „Lot Relabel", с равна стойност.
        "stock_lot_relabel",
        # ADR-0098 / ADR-0100: ПфП е фонова задача; известието — по шината.
        "queue_job",
        "bus",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/queue_job_channel.xml",
        "wizards/mrp_production_prepare_wizard_views.xml",
        "wizards/mrp_production_unprepare_wizard_views.xml",
        "wizards/mrp_production_cutting_trial_views.xml",
        "views/stock_picking_type_views.xml",
        "views/mrp_production_views.xml",
        "views/stock_picking_views.xml",
    ],
}
