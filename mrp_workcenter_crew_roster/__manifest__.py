# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
{
    "name": "Work Center Crew Roster",
    "summary": "Daily crew roster per work center shift: "
    "the single source of the work order crew",
    "version": "18.0.1.12.4",
    "category": "Manufacturing/Manufacturing",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "license": "OPL-1",
    # Зависимости по TECH_DESIGN §2. sale_mrp е МЕКА зависимост (M12) —
    # проверява се през _fields, затова не е тук. Нищо AGPL.
    "depends": [
        "mrp_workorder",
        "web_gantt",
        "hr",
        "hr_holidays",
        "resource",
        # Шината и chatter-ът на МО (Р35, Р37, Р38) — вече са в зависимостите
        # на mrp; тук са изрично, защото наследяваме ir.websocket.
        "bus",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mrp_workcenter_roster_security.xml",
        "data/ir_config_parameter_data.xml",
        "data/ir_cron_data.xml",
        "views/mrp_workcenter_roster_views.xml",
        "views/mrp_workorder_views.xml",
        "views/mrp_workorder_crew_gantt_views.xml",
        "views/mrp_workcenter_replan_batch_views.xml",
        "wizard/mrp_workcenter_plan_select_views.xml",
        "wizard/mrp_workcenter_replan_wizard_views.xml",
        "views/menus.xml",
    ],
    # Гантът — в мързеливия бандъл, като Ганта на EE mrp_workorder (§4).
    "assets": {
        "web.assets_backend_lazy": [
            "mrp_workcenter_crew_roster/static/src/crew_gantt/**/*",
        ],
        # Hoot — само файловете в static/tests/ (без `**`, за да не влезе
        # tour-ът); tour-ът е в web.assets_tests (§9.13.4).
        "web.assets_unit_tests": [
            "mrp_workcenter_crew_roster/static/tests/*",
        ],
        "web.assets_tests": [
            "mrp_workcenter_crew_roster/static/tests/tours/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
