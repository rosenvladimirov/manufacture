import * as hoot from "@odoo/hoot-dom";
import { registry } from "@web/core/registry";

/**
 * Tour на дефекта от живия тест 09.10 (19.0.1.6.1, Р32): истинският EE Гант,
 * влачене с pointer събития. Вагон C се влачи и се задържа над границата на
 * два ДОЛЕПЕНИ вагона A|B: трябва стрелка на границата и призрак „вмъкване“,
 * а B (и всичко след границата) се отмества надясно, за да се види мястото.
 * После C се пуска; местата се проверяват в Python
 * (`tests/test_crew_drop_tour.py`). Центърът е „Drop Line“. Вторият tour
 * (`crew_roster_drop_snap_tour`) пуска C в празно място (Р32, 09.10).
 */

/** Няколко кадъра — хувърът на Ганта е throttle-нат по кадри. */
async function settle(count = 3) {
    for (let i = 0; i < count; i++) {
        await hoot.animationFrame();
    }
    await hoot.delay(60);
}

function pillWrapper(name) {
    return [...document.querySelectorAll(".o_gantt_cells .o_gantt_pill_wrapper")].find(
        (el) => el.textContent.includes(name) && !el.classList.contains("o_dragged_pill_ghost")
    );
}

function rect(el) {
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), height: Math.round(r.height) };
}

/** Мести показалеца на (x, y) — събитията отиват на елемента под него. */
async function moveAt(moveTo, x, y) {
    const target = document.elementFromPoint(x, y) || document.body;
    await moveTo(target, { position: { x, y } });
    await settle();
}

/** Общите стъпки: „Plan Work Center“ → „Drop Line“ → Гантът с трите вагона. */
function openDropLineGantt() {
    return [
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
            run: "edit Drop Line",
        },
        {
            content: "Pick the work center",
            trigger: ".o-autocomplete--dropdown-menu .o-autocomplete--dropdown-item a:contains(Drop Line)",
            run: "click",
        },
        {
            content: "Open the Gantt",
            trigger: ".modal button[name=action_open_gantt].btn-primary",
            run: "click",
        },
        {
            content: "The three wagons are in the Gantt",
            trigger: ".o_gantt_view .o_gantt_pill_wrapper:contains(Wagon C)",
        },
    ];
}

registry.category("web_tour.tours").add("crew_roster_drop_tour", {
    url: "/odoo?debug=tests",
    steps: () => [
        ...openDropLineGantt(),
        {
            content: "Drag C over the A|B boundary: arrow, insert ghost, place opens; then drop",
            trigger: ".o_gantt_view .o_gantt_pill_wrapper:contains(Wagon B)",
            async run() {
                const a = pillWrapper("Wagon A");
                const b = pillWrapper("Wagon B");
                const c = pillWrapper("Wagon C");
                if (!a || !b || !c) {
                    throw new Error("Wagons A, B, C are not all rendered");
                }
                c.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
                await settle();
                const ra = rect(a);
                const rb = rect(b);
                const rc = rect(c);
                console.log(
                    "crew_drop_tour: scale",
                    document.querySelector(".o_gantt_scale_selector .scale_button_selection")?.textContent?.trim(),
                    "A",
                    JSON.stringify(ra),
                    "B",
                    JSON.stringify(rb),
                    "C",
                    JSON.stringify(rc),
                    "A.style",
                    a.style.gridColumn,
                    "B.style",
                    b.style.gridColumn,
                    "C.style",
                    c.style.gridColumn
                );
                if (Math.abs(ra.right - rb.left) > 2) {
                    throw new Error(`A and B are not adjacent on the screen: ${ra.right} vs ${rb.left}`);
                }
                // Хваща се C близо до лявия край (извън дръжката за resize),
                // за да почне призракът точно там, където е показалецът.
                const pill = c.querySelector(".o_gantt_pill");
                const grabX = rc.left + 12;
                const y = rc.top + rc.height / 2;
                const { moveTo, drop } = await hoot.drag(pill, {
                    position: { x: grabX, y },
                });
                await settle();
                await moveAt(moveTo, grabX - 5, y);
                // Задържане над границата A|B (малко вдясно от нея).
                const yAB = ra.top + ra.height / 2;
                const x = rb.left + 6;
                await moveAt(moveTo, x - 3, yAB);
                await moveAt(moveTo, x, yAB);
                const ghost = document.querySelector(".o_gantt_cells .o_drag_hover");
                const arrow = document.querySelector(".o_gantt_cells .o_crew_drop_arrow");
                const bNow = rect(pillWrapper("Wagon B"));
                console.log(
                    "crew_drop_tour: hover",
                    "ghost",
                    ghost && ghost.className,
                    ghost && ghost.style.gridColumn,
                    "arrow",
                    arrow && arrow.className,
                    arrow && JSON.stringify(rect(arrow)),
                    "B now",
                    JSON.stringify(bNow),
                    "dragging",
                    document.querySelector(".o_gantt_renderer")?.className
                );
                const errors = [];
                if (!ghost) {
                    errors.push("no drag ghost (.o_drag_hover)");
                } else if (!ghost.classList.contains("o_crew_drop_insert")) {
                    errors.push(`the ghost is not an insert: "${ghost.className}"`);
                }
                if (!arrow) {
                    errors.push("no drop arrow (.o_crew_drop_arrow)");
                } else {
                    const ar = rect(arrow);
                    if (Math.abs(ar.left - ra.right) > 3) {
                        errors.push(`the arrow is not at the A|B boundary: ${ar.left} vs ${ra.right}`);
                    }
                    // Видима: над вагоните, не под тях.
                    const zArrow = Number(getComputedStyle(arrow).zIndex);
                    const zPill = Number(getComputedStyle(a).zIndex);
                    if (!(zArrow > zPill)) {
                        errors.push(`the arrow is under the wagons: z-index ${zArrow} <= ${zPill}`);
                    }
                }
                // „Разтваряне“: B се отмества надясно, докато C виси над границата.
                if (bNow.left <= rb.left + 2) {
                    errors.push(`the place does not open: B stays at ${bNow.left} (was ${rb.left})`);
                }
                if (errors.length) {
                    await drop();
                    throw new Error("crew_drop_tour: " + errors.join("; "));
                }
                await drop();
                await settle(5);
            },
        },
        {
            content: "After the drop the arrow is gone and no wagon stays shifted",
            trigger: ".o_gantt_view:not(:has(.o_crew_drop_arrow)):not(:has(.o_crew_drop_open))",
        },
        {
            content: "The drop went through crew_drop: the Undo notification is shown",
            trigger: ".o_notification:has(.fa-undo), .o_notification_buttons button:has(.fa-undo)",
        },
    ],
});

/**
 * Р32, Росен 09.10 (19.0.1.6.1): пускане в ПРАЗНО място далеч вдясно — C не
 * остава там, а залепва за края на последната поръчка (B). При задържането:
 * призракът е „залепва“ (`o_crew_drop_snap`), стрелката (пунктир) е на края
 * на B, нищо не се разтваря. Местата — в Python (test_37).
 */
registry.category("web_tour.tours").add("crew_roster_drop_snap_tour", {
    url: "/odoo?debug=tests",
    steps: () => [
        ...openDropLineGantt(),
        {
            content: "Drag C far to an empty place: the snap arrow is at the end of B; then drop",
            trigger: ".o_gantt_view .o_gantt_pill_wrapper:contains(Wagon B)",
            async run() {
                const b = pillWrapper("Wagon B");
                const c = pillWrapper("Wagon C");
                c.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
                await settle();
                const rb = rect(b);
                const rc = rect(c);
                const pill = c.querySelector(".o_gantt_pill");
                const grabX = rc.left + 12;
                const y = rc.top + rc.height / 2;
                const { moveTo, drop } = await hoot.drag(pill, { position: { x: grabX, y } });
                await settle();
                // Четири клетки вдясно от C — празно.
                const x = grabX + 4 * (rc.right - rc.left);
                await moveAt(moveTo, x - 3, y);
                await moveAt(moveTo, x, y);
                const ghost = document.querySelector(".o_gantt_cells .o_drag_hover");
                const arrow = document.querySelector(".o_gantt_cells .o_crew_drop_arrow");
                console.log(
                    "crew_drop_snap_tour: hover",
                    ghost && ghost.className,
                    ghost && ghost.style.gridColumn,
                    arrow && arrow.className,
                    arrow && JSON.stringify(rect(arrow)),
                    "B",
                    JSON.stringify(rb)
                );
                const errors = [];
                if (!ghost?.classList.contains("o_crew_drop_snap")) {
                    errors.push(`the ghost does not snap: "${ghost?.className}"`);
                }
                if (!arrow?.classList.contains("o_crew_drop_arrow_snap")) {
                    errors.push(`no snap arrow: "${arrow?.className}"`);
                } else if (Math.abs(rect(arrow).left + 1 - rb.right) > 3) {
                    errors.push(`the snap arrow is not at the end of B: ${rect(arrow).left} vs ${rb.right}`);
                }
                if (document.querySelector(".o_gantt_cells .o_crew_drop_open")) {
                    errors.push("a wagon is shifted on a drop in an empty place");
                }
                await drop();
                await settle(5);
                if (errors.length) {
                    throw new Error("crew_drop_snap_tour: " + errors.join("; "));
                }
            },
        },
        {
            content: "The drop went through crew_drop: the Undo notification is shown",
            trigger: ".o_notification:has(.fa-undo), .o_notification_buttons button:has(.fa-undo)",
        },
    ],
});
