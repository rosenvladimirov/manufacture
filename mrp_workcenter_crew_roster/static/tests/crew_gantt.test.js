import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import { queryFirst } from "@odoo/hoot-dom";
import { animationFrame, mockDate } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    mockService,
    models,
    MockServer,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { mountGanttView } from "@web_gantt/../tests/web_gantt_test_helpers";
import { CREW_REPLAN_WIZARD_ACTION } from "@mrp_workcenter_crew_roster/crew_gantt/crew_gantt_controller";
import { CrewGanttModel } from "@mrp_workcenter_crew_roster/crew_gantt/crew_gantt_model";

describe.current.tags("desktop");

// Минималните модели за монтиране на Ганта „Планирай център“.
class Workorder extends models.Model {
    _name = "mrp.workorder";

    name = fields.Char();
    date_start = fields.Datetime();
    date_finished = fields.Datetime();
    workcenter_id = fields.Many2one({ string: "Work Center", relation: "mrp.workcenter" });

    _records = [
        {
            id: 1,
            name: "Cut",
            date_start: "2026-10-05 06:00:00",
            date_finished: "2026-10-05 08:00:00",
            workcenter_id: 1,
        },
    ];
}

class Workcenter extends models.Model {
    _name = "mrp.workcenter";

    name = fields.Char();

    _records = [{ id: 1, name: "Line 1" }];
}

class Roster extends models.Model {
    _name = "mrp.workcenter.roster";
}

// Партидата: само полетата, които Гантът чете (фаза 2, §9.13.4).
class ReplanBatch extends models.Model {
    _name = "mrp.workcenter.replan.batch";

    crew_can_undo = fields.Boolean();
    state = fields.Selection({
        selection: [
            ["applied", "Applied"],
            ["undone", "Undone"],
            ["partial", "Partially Undone"],
        ],
    });

    _records = [{ id: 9, crew_can_undo: true, state: "applied" }];
}

defineMailModels();
defineModels([Workorder, Workcenter, Roster, ReplanBatch]);

const ARCH = `<gantt js_class="mrp_crew_gantt" date_start="date_start" date_stop="date_finished"/>`;

// Моделът се проверява през прототипа: така се тества точно нашият код
// върху стандартния `GanttModel`, без влачене в DOM.
const META = {
    resModel: "mrp.workorder",
    dateStartField: "date_start",
    dateStopField: "date_finished",
    groupedBy: ["workcenter_id", "employee_assigned_ids"],
};

test("model: the crew is cut from the schedule data", () => {
    const data = CrewGanttModel.prototype._scheduleToData.call(
        { metaData: META },
        {
            date_start: "2026-10-05 06:00:00",
            date_finished: "2026-10-05 08:00:00",
            workcenter_id: 2,
            employee_assigned_ids: [7],
            name: "ignored",
        }
    );
    expect(data).toEqual({
        date_start: "2026-10-05 06:00:00",
        date_finished: "2026-10-05 08:00:00",
        workcenter_id: 2,
    });
});

test("model: the drag writes with the crew_gantt_drag flag", async () => {
    const calls = [];
    const fake = {
        metaData: META,
        orm: {
            write: (...args) => {
                calls.push(args);
                return true;
            },
        },
    };
    await CrewGanttModel.prototype._reschedule.call(
        fake,
        [1],
        { date_start: "2026-10-05 06:00:00" },
        { lang: "en_US" }
    );
    expect(calls).toEqual([
        [
            "mrp.workorder",
            [1],
            { date_start: "2026-10-05 06:00:00" },
            { context: { lang: "en_US", crew_gantt_drag: true } },
        ],
    ]);
});

test("controller: Recompute only with a work center in the context", async () => {
    mockDate("2026-10-05 07:00:00");
    onRpc("mrp.workcenter.roster", "action_crew_recompute", ({ args, kwargs }) => {
        // 19.0.1.6.1: методът не е @api.model — първият аргумент са ids ([]).
        expect.step(["recompute", args, kwargs.context.crew_workcenter_id]);
        return { type: "ir.actions.act_window_close" };
    });
    onRpc("get_gantt_data", () => {
        expect.step("get_gantt_data");
    });
    await mountGanttView({
        arch: ARCH,
        resModel: "mrp.workorder",
        context: { crew_workcenter_id: 1 },
    });
    expect.verifySteps(["get_gantt_data"]);
    expect(".o_crew_gantt_button_recompute").toHaveCount(1);
    await contains(".o_crew_gantt_button_recompute").click();
    // След затварянето на отчета Гантът се презарежда.
    expect.verifySteps([["recompute", [[]], 1], "get_gantt_data"]);
});

test("controller: no Recompute without a work center", async () => {
    mockDate("2026-10-05 07:00:00");
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder" });
    expect(".o_gantt_view").toHaveCount(1);
    expect(".o_crew_gantt_button_recompute").toHaveCount(0);
});

//-----------------------------------------------------------------------------
// Фаза 2 (TECH_DESIGN §9.13.4, §9.13.6 т. 34): „Rearrange Plan“ и Undo
//-----------------------------------------------------------------------------

const BATCH = "mrp.workcenter.replan.batch";
const REPORT = {
    type: "ir.actions.act_window",
    res_model: BATCH,
    res_id: 9,
    views: [[false, "form"]],
    target: "new",
};

/** Стъпките на партидата: четенето (полетата) и отмяната. */
function stepBatchRpcs() {
    onRpc(BATCH, "read", ({ args }) => {
        expect.step(["read", args[1]]);
    });
    onRpc(BATCH, "action_undo", ({ args }) => {
        expect.step(["action_undo", args[0]]);
        MockServer.env[BATCH].write(args[0], { state: "undone", crew_can_undo: false });
        return true;
    });
    onRpc("get_gantt_data", () => {
        expect.step("get_gantt_data");
    });
}

/**
 * Мокнатият action service: съветникът се „затваря“ с `infos` (или без),
 * отчетът — веднага. `onClose` не се чака, като в истинския `_removeDialog`.
 * Контекстите, подадени на съветника, се пазят в `calls`.
 */
function mockActions({ wizardInfos } = {}) {
    const calls = [];
    mockService("action", {
        doAction(action, options = {}) {
            if (action === CREW_REPLAN_WIZARD_ACTION) {
                calls.push(options.additionalContext);
                expect.step("wizard");
                options.onClose?.(wizardInfos);
            } else {
                expect.step(["report", action.res_id]);
                options.onClose?.();
            }
            return Promise.resolve(true);
        },
    });
    return calls;
}

test("Г11: Rearrange Plan is shown without a work center; only the crew keys reach the wizard", async () => {
    mockDate("2026-10-05 07:00:00");
    const calls = mockActions();
    onRpc("get_gantt_data", () => {
        expect.step("get_gantt_data");
    });
    await mountGanttView({
        arch: ARCH,
        resModel: "mrp.workorder",
        context: { default_start_date: "2026-09-28", default_stop_date: "2026-10-11" },
    });
    expect.verifySteps(["get_gantt_data"]);
    expect(".o_crew_gantt_button_recompute").toHaveCount(0);
    expect(".o_crew_gantt_button_replan").toHaveCount(1);
    await contains(".o_crew_gantt_button_replan").click();
    // Без партида (Cancel/X) — само презареждане.
    await expect.waitForSteps(["wizard", "get_gantt_data"]);
    // Началото на изгледа (28.09) е в миналото → днес; нищо от контекста
    // на действието (default_*) не стига до съветника (Ф3).
    expect(calls).toEqual([
        {
            crew_workcenter_ids: [],
            crew_date_from: "2026-10-05",
            crew_date_to: "2026-10-11",
            crew_from_gantt: true,
        },
    ]);
});

test("Г11: the work center of the Gantt and a future period reach the wizard as they are", async () => {
    mockDate("2026-10-05 07:00:00");
    const calls = mockActions();
    await mountGanttView({
        arch: ARCH,
        resModel: "mrp.workorder",
        context: {
            crew_workcenter_id: 1,
            search_default_workcenter_id: 1,
            default_start_date: "2026-10-12",
            default_stop_date: "2026-10-18",
        },
    });
    await contains(".o_crew_gantt_button_replan").click();
    await expect.waitForSteps(["wizard"]);
    expect(calls).toEqual([
        {
            crew_workcenter_ids: [1],
            crew_date_from: "2026-10-12",
            crew_date_to: "2026-10-18",
            crew_from_gantt: true,
        },
    ]);
});

test("Г11: two quick clicks on Rearrange Plan open the wizard once", async () => {
    mockDate("2026-10-05 07:00:00");
    const calls = [];
    let open;
    // Съветникът се „отваря“ бавно: вторият клик идва, докато първият чака.
    mockService("action", {
        doAction(action, options = {}) {
            calls.push(options.additionalContext);
            expect.step("wizard");
            return new Promise((resolve) => {
                open = resolve;
            });
        },
    });
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder" });
    const button = queryFirst(".o_crew_gantt_button_replan");
    button.click();
    button.click();
    await animationFrame();
    expect.verifySteps(["wizard"]);
    open(true);
    await animationFrame();
    // След отварянето бутонът пак работи.
    button.click();
    await animationFrame();
    expect.verifySteps(["wizard"]);
    expect(calls).toHaveLength(2);
});

test("Г12: after the report of Recompute a sticky Undo; two quick clicks undo once, then the Gantt reloads", async () => {
    mockDate("2026-10-05 07:00:00");
    ReplanBatch._records = [{ id: 9, crew_can_undo: true, state: "applied" }];
    mockActions();
    stepBatchRpcs();
    onRpc("mrp.workcenter.roster", "action_crew_recompute", () => REPORT);
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder", context: { crew_workcenter_id: 1 } });
    expect.verifySteps(["get_gantt_data"]);
    await contains(".o_crew_gantt_button_recompute").click();
    await expect.waitForSteps([["report", 9], "get_gantt_data", ["read", ["crew_can_undo"]]]);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("Plan recomputed.");
    const button = queryFirst(".o_notification button:contains(Undo)");
    // Два бързи клика: едно action_undo.
    button.click();
    button.click();
    await expect.waitForSteps([["action_undo", [9]], ["read", ["state"]], "get_gantt_data"]);
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("Г12: no Undo when the batch was already undone from the report", async () => {
    mockDate("2026-10-05 07:00:00");
    ReplanBatch._records = [{ id: 9, crew_can_undo: false, state: "undone" }];
    mockActions();
    stepBatchRpcs();
    onRpc("mrp.workcenter.roster", "action_crew_recompute", () => REPORT);
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder", context: { crew_workcenter_id: 1 } });
    expect.verifySteps(["get_gantt_data"]);
    await contains(".o_crew_gantt_button_recompute").click();
    await expect.waitForSteps([["report", 9], "get_gantt_data", ["read", ["crew_can_undo"]]]);
    await animationFrame();
    expect(".o_notification").toHaveCount(0);
});

test("Г12: a partial undo warns to see the report", async () => {
    mockDate("2026-10-05 07:00:00");
    ReplanBatch._records = [{ id: 9, crew_can_undo: true, state: "applied" }];
    mockActions();
    onRpc(BATCH, "action_undo", ({ args }) => {
        MockServer.env[BATCH].write(args[0], { state: "partial", crew_can_undo: false });
        return true;
    });
    onRpc("mrp.workcenter.roster", "action_crew_recompute", () => REPORT);
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder", context: { crew_workcenter_id: 1 } });
    await contains(".o_crew_gantt_button_recompute").click();
    await expect.waitForSteps([["report", 9]]);
    await contains(".o_notification button:contains(Undo)").click();
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText(
        "Some work orders could not be returned; see the report."
    );
});

test("Г13: the wizard closes with the batch: the report opens, then the Undo", async () => {
    mockDate("2026-10-05 07:00:00");
    ReplanBatch._records = [{ id: 9, crew_can_undo: true, state: "applied" }];
    mockActions({ wizardInfos: { crew_batch_id: 9 } });
    stepBatchRpcs();
    onRpc(BATCH, "action_open_report", ({ args }) => {
        expect.step(["action_open_report", args[0]]);
        return REPORT;
    });
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder" });
    expect.verifySteps(["get_gantt_data"]);
    await contains(".o_crew_gantt_button_replan").click();
    await expect.waitForSteps([
        "wizard",
        ["action_open_report", [9]],
        "get_gantt_data",
        ["report", 9],
        "get_gantt_data",
        ["read", ["crew_can_undo"]],
    ]);
    await animationFrame();
    expect(".o_notification_content").toHaveText("Plan rearranged.");
    await contains(".o_notification button:contains(Undo)").click();
    await expect.waitForSteps([["action_undo", [9]], ["read", ["state"]], "get_gantt_data"]);
});

test("Г13: the wizard closes without a batch (Cancel): only a reload", async () => {
    mockDate("2026-10-05 07:00:00");
    mockActions();
    stepBatchRpcs();
    onRpc(BATCH, "action_open_report", () => {
        expect.step("action_open_report");
        return REPORT;
    });
    await mountGanttView({ arch: ARCH, resModel: "mrp.workorder" });
    expect.verifySteps(["get_gantt_data"]);
    await contains(".o_crew_gantt_button_replan").click();
    await expect.waitForSteps(["wizard", "get_gantt_data"]);
    await animationFrame();
    expect.verifySteps([]);
    expect(".o_notification").toHaveCount(0);
});
