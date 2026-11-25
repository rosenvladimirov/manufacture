# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
{
    "name": "Work Center Crew Roster from Crew Rotation",
    "summary": "The crew on shift fills the roster of the work centers of its rotation",
    "version": "18.0.1.4.0",
    "category": "Manufacturing/Manufacturing",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "license": "OPL-1",
    # Мост: нарядът по център и ротациите на бригадите не зависят един от друг.
    "depends": ["mrp_workcenter_crew_roster", "planning_crew_rotation"],
    "data": [
        "views/mrp_workcenter_views.xml",
        "views/planning_crew_rotation_views.xml",
        "views/mrp_workcenter_roster_views.xml",
    ],
    "assets": {
        # 18: Shop Floor е преписан върху панела на 18 (без Edit Operators и offcanvas)
        "web.assets_backend": [
            "mrp_workcenter_crew_roster_planning/static/src/shop_floor/*",
        ],
        "web.assets_tests": [
            "mrp_workcenter_crew_roster_planning/static/tests/tours/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
