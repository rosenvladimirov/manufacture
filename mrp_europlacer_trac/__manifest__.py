# -*- coding: utf-8 -*-
{
    "name": "Europlacer Traceability (data models)",
    "version": "19.0.1.0.0",
    "summary": "Schema-only europlacer.trac / europlacer.trac.line tables for O11->O19 data transfer",
    "description": """
Europlacer Traceability — data models only
==========================================
Schema carriers for the ``europlacer.trac`` and ``europlacer.trac.line`` tables,
ported from the Odoo 11 dXFactory ``europlacer`` connector for full-compatibility
transfer of historical traceability records into Odoo 19.

Contains ONLY the field definitions (data-carrier tables) — deliberately no
data-collection logic (no file parsing, watchdog, queue_job populate, cron).
""",
    "author": "dXFactory Ltd., Rosen Vladimirov",
    "website": "https://github.com/rosenvladimirov/manufacture-experts",
    "category": "Manufacture",
    "license": "AGPL-3",
    "depends": ["mrp", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/europlacer_trac_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
    'post_init_hook': 'post_init_hook',
}
