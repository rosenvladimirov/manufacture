import { registry } from "@web/core/registry";

/**
 * Tour на фаза 2 (TECH_DESIGN §9.13.5): „Plan Work Center“ → Гантът →
 * „Rearrange Plan“ → потвърждение → отчетът → Undo → потвърждение →
 * „Undone“ → обратно в Ганта; после още веднъж, но отчетът се затваря без
 * Undo и се отменя от лепкавото известие в Ганта. Местата на поръчките след Undo се проверяват
 * в Python (`tests/test_crew_tour.py`). Центърът е „Tour Line“. Селекторите
 * не зависят от езика (базата е с bg_BG): потвърждението е активният
 * диалог, състоянието е `data-value`.
 */
registry.category("web_tour.tours").add("crew_roster_replan_tour", {
    url: "/odoo?debug=tests",
    steps: () => [
        {
            content: "Open Manufacturing",
            trigger: '.o_app[data-menu-xmlid="mrp.menu_mrp_root"]',
            run: "click",
        },
        {
            content: "Open Planning",
            trigger: '.o-dropdown[data-menu-xmlid="mrp.mrp_planning_menu_root"]',
            run: "click",
        },
        {
            content: "Plan Work Center",
            trigger:
                '.o-dropdown-item[data-menu-xmlid="mrp_workcenter_crew_roster.menu_mrp_workcenter_plan_select"]',
            run: "click",
        },
        {
            content: "Type the work center",
            trigger: ".modal .o_field_widget[name=workcenter_ids] input",
            run: "edit Tour Line",
        },
        {
            content: "Pick the work center",
            trigger: ".o-autocomplete--dropdown-menu .o-autocomplete--dropdown-item a:contains(Tour Line)",
            run: "click",
        },
        {
            content: "Open the Gantt",
            trigger: ".modal button[name=action_open_gantt].btn-primary",
            run: "click",
        },
        {
            content: "Rearrange Plan",
            trigger: ".o_gantt_view .o_crew_gantt_button_replan",
            run: "click",
        },
        {
            content: "The work center of the Gantt is in the wizard",
            trigger: ".modal .o_field_widget[name=workcenter_ids] .o_tag:contains(Tour Line)",
        },
        {
            content: "Rearrange",
            trigger: ".modal button[name=action_apply]",
            run: "click",
        },
        {
            content: "Confirm",
            trigger: ".o_dialog:not(.o_inactive_modal) .modal-footer button.btn-primary",
            run: "click",
        },
        {
            content: "The report shows the work orders of the batch",
            trigger: ".modal .o_field_widget[name=report_html] table tbody tr",
        },
        {
            content: "Undo",
            trigger: ".modal button[name=action_undo_report]",
            run: "click",
        },
        {
            content: "Confirm the undo",
            trigger: ".o_dialog:not(.o_inactive_modal) .modal-footer button.btn-primary",
            run: "click",
        },
        {
            content: "The report is reopened as Undone, without Undo",
            trigger:
                ".modal:not(:has(button[name=action_undo_report])) .o_statusbar_status .o_arrow_button_current[data-value=undone]",
        },
        {
            content: "Close the report",
            trigger: ".modal .btn-close",
            run: "click",
        },
        {
            content: "Back in the Gantt",
            trigger: "body:not(:has(.modal)) .o_gantt_view .o_crew_gantt_button_replan",
        },
        // Втори път: отчетът се затваря без Undo → лепкавото известие в Ганта.
        {
            content: "Rearrange Plan again",
            trigger: "body:not(:has(.modal)) .o_gantt_view .o_crew_gantt_button_replan",
            run: "click",
        },
        {
            content: "Rearrange again",
            trigger: ".modal button[name=action_apply]",
            run: "click",
        },
        {
            content: "Confirm again",
            trigger: ".o_dialog:not(.o_inactive_modal) .modal-footer button.btn-primary",
            run: "click",
        },
        {
            content: "Close the report without Undo",
            trigger: ".modal:has(button[name=action_undo_report]) .btn-close",
            run: "click",
        },
        {
            content: "Undo from the sticky notification of the Gantt",
            trigger: "body:not(:has(.modal)) .o_notification .o_notification_buttons button:has(.fa-undo)",
            run: "click",
        },
        {
            content: "The notification is closed after the undo",
            trigger: "body:not(:has(.o_notification)) .o_gantt_view",
        },
    ],
});
