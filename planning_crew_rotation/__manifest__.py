# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
{
    "name": "Planning Crew Rotation",
    "summary": "Crews of the company shift schedule (A, B, C, D) fill the Planning "
               "shifts of their people",
    "version": "18.0.1.3.1",
    "category": "Human Resources/Planning",
    "author": "Rosen Vladimirov, Terraros Commerce Ltd.",
    "license": "OPL-1",
    # Planning носи смените и шаблоните; hr_holidays — отпуските, по които
    # графикът се пренарежда със заместници.
    "depends": ["planning", "hr_holidays", "hr_contract"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "wizard/planning_crew_rotation_generate_views.xml",
        "views/planning_crew_rotation_views.xml",
        "views/hr_employee_views.xml",
        "views/planning_slot_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
