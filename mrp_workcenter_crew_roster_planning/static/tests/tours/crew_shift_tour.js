/** Shop Floor „Човеци“ / „Смяна/Бригада“ (Росен 15.10.2026) — през истинския интерфейс.
 *  Без надписи в селекторите — езикът на браузъра може да е български. */
import { registry } from "@web/core/registry";

const CREW = "Extrusion (shift tour) / A";
const crewLi = `.o_crew_shift_crews li[name='${CREW}']`;

registry.category("web_tour.tours").add("crew_shift_shop_floor", {
    steps: () => [
        // 18: изборът на центрове се отваря сам при първото влизане; панелът с хората — с бутона
        { trigger: '.form-check:has(input[name="Extruder (shift tour)"])', run: "click" },
        { trigger: '.form-check:has(input[name="Extruder (shift tour)"]:checked)' },
        { trigger: "footer.modal-footer button.btn-primary", run: "click" },
        { trigger: '.o_control_panel_actions button:contains("Extruder (shift tour)")', run: "click" },
        { trigger: 'button[name="employeePanelButton"]', run: "click" },
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_people.btn-primary" },
        { trigger: ".o_crew_shift_kick" },
        // „Смяна/Бригада“: в списъка — бригади; бутонът долу е „Редактиране на бригади“
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_crew", run: "click" },
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_crew.btn-primary" },
        { trigger: ".o_mrp_employees_panel:not(:has(.o_crew_shift_add_operator))" },
        { trigger: ".o_crew_shift_edit", run: "click" },
        { trigger: `.o_crew_shift_list li[name='${CREW}']`, run: "click" },
        { trigger: `.o_crew_shift_list li[name='${CREW}'].active` },
        { trigger: ".modal-footer button.btn-primary", run: "click" },
        // ПИН на бригадира: името; грешен ПИН — не; верният — да
        { trigger: ".o_crew_shift_pin_leader:contains('Tour leader A')" },
        { trigger: ".popup-numpad button:contains(9)", run: "click" },
        { trigger: ".modal-footer div.btn-primary", run: "click" },
        { trigger: ".o_notification" },
        { trigger: ".popup-numpad button:contains(C)", run: "click" },
        { trigger: ".popup-numpad button:contains(1)", run: "click" },
        { trigger: ".popup-numpad button:contains(2)", run: "click" },
        { trigger: ".popup-numpad button:contains(3)", run: "click" },
        { trigger: ".popup-numpad button:contains(4)", run: "click" },
        { trigger: ".modal-footer div.btn-primary", run: "click" },
        { trigger: `${crewLi}.o_crew_shift_selected` },
        { trigger: `${crewLi} .o_crew_shift_leader_name:contains('Tour leader A')` },
        // старт върху поръчката — избраната бригада
        { trigger: '.o_control_panel_actions button.active:contains("Extruder (shift tour)")' },
        { trigger: ".o_mrp_display_record .card-header", run: "click" },
        { trigger: `${crewLi} .o_tag:contains('Extruder (shift tour)')` },
        // „Изритай“ → всички → „Да“
        { trigger: ".o_crew_shift_kick", run: "click" },
        { trigger: ".o_crew_shift_kick_all", run: "click" },
        { trigger: ".modal-footer button.btn-primary", run: "click" },
        { trigger: `${crewLi}:not(:has(.o_tag))` },
        // махане на бригадата → „Не“ — остава
        { trigger: ".o_crew_shift_edit", run: "click" },
        { trigger: `.o_crew_shift_list li[name='${CREW}'].active`, run: "click" },
        { trigger: `.o_crew_shift_list li[name='${CREW}']:not(.active)` },
        { trigger: ".modal-footer button.btn-primary", run: "click" },
        { trigger: `.modal-body:contains('${CREW}')` },
        { trigger: ".modal-footer button.btn-secondary", run: "click" },
        { trigger: "body:not(:has(.modal))" },
        { trigger: crewLi },
        // „Човеци“ — хората, бригадирът с етикет
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_people", run: "click" },
        { trigger: ".o_crew_shift_add_operator" },
        { trigger: ".o_mrp_employees_panel li:contains('Tour leader A') .o_crew_shift_leader" },
        { trigger: ".o_mrp_employees_panel li:contains('Tour worker A2')" },
        // „Групи“: бригадирът дели хората на 2 групи с ПИН-а си
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_group", run: "click" },
        { trigger: ".o_crew_shift_toolbar .o_crew_shift_group.btn-primary" },
        { trigger: ".o_crew_shift_edit_groups", run: "click" },
        { trigger: ".o_crew_shift_group_person[name='Tour leader A'] .o_crew_shift_group_btn[data-group='1']", run: "click" },
        { trigger: ".o_crew_shift_group_person[name='Tour worker A2'] .o_crew_shift_group_btn[data-group='2']", run: "click" },
        { trigger: ".o_crew_shift_group_person[name='Tour worker A2'] .o_crew_shift_group_btn[data-group='2'].active" },
        { trigger: ".modal-footer button.btn-primary", run: "click" },
        { trigger: ".o_crew_shift_pin_leader:contains('Tour leader A')" },
        { trigger: ".popup-numpad button:contains(1)", run: "click" },
        { trigger: ".popup-numpad button:contains(2)", run: "click" },
        { trigger: ".popup-numpad button:contains(3)", run: "click" },
        { trigger: ".popup-numpad button:contains(4)", run: "click" },
        { trigger: ".modal-footer div.btn-primary", run: "click" },
        { trigger: ".o_crew_shift_groups li:eq(1):contains('Tour worker A2')" },
        { trigger: ".o_crew_shift_groups li:eq(1)", run: "click" },
        { trigger: ".o_crew_shift_groups li:eq(1).o_crew_shift_selected" },
        // старт — само избраната група (работникът); бригадирът не тръгва
        { trigger: ".o_mrp_display_record .card-header", run: "click" },
        { trigger: ".o_crew_shift_groups li:eq(1) .o_tag:contains('Extruder (shift tour)')" },
        { trigger: ".o_crew_shift_groups li:eq(0):not(:has(.o_tag))" },
        // „Изритай“ → избраните
        { trigger: ".o_crew_shift_kick", run: "click" },
        { trigger: ".o_crew_shift_kick_selected", run: "click" },
        { trigger: ".o_crew_shift_groups li:eq(1):not(:has(.o_tag))" },
        // махане на група в редактора: 3-та група, „× 2“ — по-горната слиза на 2
        { trigger: ".o_crew_shift_edit_groups", run: "click" },
        { trigger: ".o_crew_shift_add_group", run: "click" },
        { trigger: ".o_crew_shift_group_person[name='Tour worker A2'] .o_crew_shift_group_btn[data-group='3']", run: "click" },
        { trigger: ".o_crew_shift_remove_group[data-group='2']", run: "click" },
        { trigger: ".o_crew_shift_group_person[name='Tour worker A2'] .o_crew_shift_group_btn[data-group='2'].active" },
        { trigger: ".modal-body:not(:has(.o_crew_shift_group_btn[data-group='3']))" },
        // „Изчисти групите“ — никой няма група
        { trigger: ".o_crew_shift_clear_groups", run: "click" },
        { trigger: ".modal-body:not(:has(.o_crew_shift_group_btn.active))" },
        { trigger: ".modal-header .btn-close", run: "click" },
        // махане на група от списъка: „×“ → потвърждение → ПИН на бригадира
        { trigger: ".o_crew_shift_groups li:eq(1) .o_crew_shift_group_remove", run: "click" },
        { trigger: ".modal-footer button.btn-primary", run: "click" },
        { trigger: ".o_crew_shift_pin_leader:contains('Tour leader A')" },
        { trigger: ".popup-numpad button:contains(1)", run: "click" },
        { trigger: ".popup-numpad button:contains(2)", run: "click" },
        { trigger: ".popup-numpad button:contains(3)", run: "click" },
        { trigger: ".popup-numpad button:contains(4)", run: "click" },
        { trigger: ".modal-footer div.btn-primary", run: "click" },
        { trigger: ".o_crew_shift_groups:not(:has(li:contains('Tour worker A2')))" },
        { trigger: ".o_crew_shift_groups li:contains('Tour leader A')" },
    ],
});
