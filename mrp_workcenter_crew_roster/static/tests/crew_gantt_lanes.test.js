import { waitForChannels } from "@bus/../tests/bus_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { keyDown, keyUp, queryAll, queryFirst, waitFor } from "@odoo/hoot-dom";
import { advanceTime, animationFrame, mockDate } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    MockServer,
    mockService,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import {
    dragPill,
    getCell,
    getCellColorProperties,
    getPillWrapper,
    mountGanttView,
    resizePill,
} from "@web_gantt/../tests/web_gantt_test_helpers";
import { serializeDateTime } from "@web/core/l10n/dates";
import { CrewGanttModel } from "@mrp_workcenter_crew_roster/crew_gantt/crew_gantt_model";
import { computeInsertion } from "@mrp_workcenter_crew_roster/crew_gantt/crew_lane_insert";
import {
    crewColsTemplate,
    crewCovered,
    crewHiddenCols,
} from "@mrp_workcenter_crew_roster/crew_gantt/crew_off_time";

describe.current.tags("desktop");

// Гантът с писти (TECH_DESIGN §9.4, Hoot Г1–Г10): мокнат сървър.
// В 18 заглавието на групата в мащаб „ден“ е "dd MMMM yyyy" (в 19 — "DDD").
const DAY = "05 October 2026";

class Workorder extends models.Model {
    _name = "mrp.workorder";

    name = fields.Char();
    date_start = fields.Datetime();
    date_finished = fields.Datetime();
    workcenter_id = fields.Many2one({ string: "Work Center", relation: "mrp.workcenter" });
    crew_lane = fields.Integer({ string: "Lane" });
    state = fields.Selection({
        selection: [
            ["ready", "Ready"],
            ["progress", "In Progress"],
            ["done", "Finished"],
        ],
    });
    crew_is_overstretched = fields.Boolean();
    crew_dep_conflict = fields.Boolean();
    crew_center_durations = fields.Json();
}

class Workcenter extends models.Model {
    _name = "mrp.workcenter";

    name = fields.Char();

    _records = [{ id: 1, name: "Line 1" }];
}

class LaneLock extends models.Model {
    _name = "mrp.workcenter.lane.lock";
}

class ReplanBatch extends models.Model {
    _name = "mrp.workcenter.replan.batch";

    // Г14: известието след „Recompute“ чете `crew_can_undo` (фаза 2).
    crew_can_undo = fields.Boolean();

    _records = [{ id: 9, crew_can_undo: true }];
}

class Roster extends models.Model {
    _name = "mrp.workcenter.roster";
}

defineMailModels();
defineModels([Workorder, Workcenter, LaneLock, ReplanBatch, Roster]);

const ARCH = `
    <gantt js_class="mrp_crew_gantt" date_start="date_start" date_stop="date_finished"
        default_scale="day"
        default_group_by="workcenter_id,crew_lane" display_unavailability="1"
        precision="{'day': 'hour:quarter'}">
        <field name="state"/>
        <field name="crew_lane"/>
        <field name="workcenter_id"/>
        <field name="crew_is_overstretched"/>
        <field name="crew_dep_conflict"/>
        <field name="crew_center_durations"/>
    </gantt>`;

/** Поръчка в писта: часовете са в UTC (mockDate е с часова зона 0). */
function wo(id, name, lane, from, to, extra = {}) {
    return {
        id,
        name,
        workcenter_id: 1,
        crew_lane: lane,
        state: "ready",
        date_start: `2026-10-05 ${from}:00`,
        date_finished: `2026-10-05 ${to}:00`,
        ...extra,
    };
}

/** „Сега“ на мокнатия сървър (часовникът на Hoot), като `server_now`. */
function nowString(seconds = 0) {
    return serializeDateTime(luxon.DateTime.now().plus({ seconds }));
}

/** Мокнатият сървър на пистите: M21 + проекция + ключалки. */
function mockCrewServer({
    lanes = { 1: 2 },
    locks = [],
    unavailable = [],
    preview = () => ({}),
    stepPreview = true,
} = {}) {
    const state = {
        preview,
        drop: () => ({ status: "done", batch_id: 7, moves: [], notes: [] }),
        showOffTime: false,
    };
    onRpc("get_gantt_data", ({ parent }) => {
        const result = parent();
        expect.step("get_gantt_data");
        result.crew_lanes = lanes;
        result.crew_locks = locks;
        result.server_now = nowString();
        result.unavailabilities.workcenter_id = { 1: unavailable };
        result.crew_show_off_time = state.showOffTime;
        return result;
    });
    onRpc("crew_gantt_set_show_off_time", ({ args }) => {
        expect.step(["crew_gantt_set_show_off_time", args[0]]);
        state.showOffTime = args[0];
        return args[0];
    });
    onRpc("crew_train_preview", ({ args }) => {
        if (stepPreview) {
            expect.step("crew_train_preview");
        }
        return { server_now: nowString(), records: state.preview(args[0]) || {} };
    });
    onRpc("crew_lane_acquire", () => ({ ok: true, expires_at: "2026-10-05 07:01:00" }));
    onRpc("crew_lane_ping", () => ({ ok: true, expires_at: "2026-10-05 07:01:00" }));
    onRpc("crew_lane_release", () => {
        expect.step("crew_lane_release");
        return 1;
    });
    onRpc("crew_drop", ({ args, kwargs }) => {
        const call = { id: args[0][0] };
        // 1.5.5 (Р33 изменено): без съгласие — само мястото на пускането;
        // всеки друг аргумент (напр. confirm/token) счупва проверката.
        for (const key of Object.keys(kwargs)) {
            if (key !== "context") {
                call[key] = kwargs[key];
            }
        }
        expect.step(["crew_drop", call]);
        return state.drop(call);
    });
    onRpc("write", ({ args, kwargs }) => {
        expect.step(["write", args[1], Boolean(kwargs.context?.crew_gantt_drag)]);
        return true;
    });
    onRpc("copy", () => {
        expect.step("copy");
        return [99];
    });
    return state;
}

async function mountCrewGantt() {
    await mountGanttView({
        arch: ARCH,
        resModel: "mrp.workorder",
        context: { default_start_date: "2026-10-05", default_stop_date: "2026-10-05" },
    });
}

beforeEach(() => {
    mockDate("2026-10-05 07:00:00", 0);
    patchWithCleanup(CrewGanttModel.prototype, {
        setup() {
            super.setup(...arguments);
            this.crewTab = "my-tab";
        },
    });
});

test("Г1: the empty lane is shown with its label and the unavailability of the center; a drop calls crew_drop", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer({
        // Втори интервал: EE оцветява частична клетка само ако има следващ.
        unavailable: [
            { start: "2026-10-05 12:00:00", stop: "2026-10-05 12:30:00" },
            { start: "2026-10-05 13:00:00", stop: "2026-10-05 13:15:00" },
        ],
    });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(queryAll(".o_gantt_row_header .o_gantt_row_title").map((el) => el.textContent.trim())).toEqual([
        "Line 1",
        "Lane 1",
        "Lane 2",
    ]);
    // Неработното време на центъра е и в празната писта (Г3).
    expect(getCellColorProperties(`12 ${DAY}`, "Lane 2").length).toBeGreaterThan(0);
    expect(getCellColorProperties(`10 ${DAY}`, "Lane 2")).toEqual([]);

    const { drop } = await dragPill("WO A");
    await drop({ column: `10 ${DAY}`, row: "Lane 2", part: 1 });
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 1,
                workcenter_id: 1,
                lane: 2,
                after_workorder_id: false,
                date_start: "2026-10-05 10:00:00",
                snap: true,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г2: computeInsertion — free, insert with k and blocked by a started wagon", () => {
    const h = (hours) => hours * 3600000;
    const wagons = [
        { id: 1, start: h(8), stop: h(9), started: false },
        { id: 2, start: h(9), stop: h(10), started: false },
        { id: 3, start: h(12), stop: h(13), started: true },
    ];
    // Свободно: 10:00–11:00 не застъпва нищо.
    expect(computeInsertion(wagons, h(10), h(1))).toMatchObject({
        mode: "free",
        k: 2,
        afterId: false,
        dateStart: h(10),
        blocked: false,
    });
    // 09:15 → k = 1 (средата на 2 е 09:30), след вагон 1.
    expect(computeInsertion(wagons, h(9.25), h(1))).toMatchObject({
        mode: "insert",
        k: 1,
        afterId: 1,
        dateStart: null,
        blocked: false,
    });
    // k = 0: от min(T, началото на първия).
    expect(computeInsertion(wagons, h(7.5), h(1))).toMatchObject({
        mode: "insert",
        k: 0,
        afterId: false,
        dateStart: h(7.5),
    });
    // Веригата стига до започнатия вагон 3 → блокирано.
    expect(computeInsertion(wagons, h(9.25), h(3))).toMatchObject({
        mode: "insert",
        k: 1,
        blocked: true,
        blockerId: 3,
    });
});

test("Г2b: computeInsertion — adjacent wagons on half-day cells: the ghost over B inserts after A", () => {
    // Дефектът от живия тест 09.10 (19.0.1.6.1): A 08–12 | B 12–17 са
    // долепени, клетката е половин ден (A — колона 17, B — колона 18). C е
    // 1 ч и призракът е върху клетката на B, но T пази часа на C — 20:00.
    const h = (hours) => hours * 3600000;
    const wagons = [
        { id: 1, start: h(8), stop: h(12), started: false, col: [17, 18] },
        { id: 2, start: h(12), stop: h(17), started: false, col: [18, 19] },
    ];
    // По часовете 20:00–21:00 не застъпва нищо — затова стрелка нямаше.
    expect(computeInsertion(wagons, h(20), h(1))).toMatchObject({ mode: "free" });
    // По колоните призракът [18, 19) е върху B: вмъкване след A, B се бута.
    expect(computeInsertion(wagons, h(20), h(1), [18, 19])).toMatchObject({
        mode: "insert",
        k: 1,
        afterId: 1,
        dateStart: null,
        blocked: false,
        pushedIds: [2],
    });
    // Призракът върху A → преди A; веригата бута и двата.
    expect(computeInsertion(wagons, h(8), h(1), [17, 18])).toMatchObject({
        mode: "insert",
        k: 0,
        afterId: false,
        dateStart: h(8),
        pushedIds: [1, 2],
    });
    // Призракът след B → свободно, k = 2.
    expect(computeInsertion(wagons, h(20), h(1), [19, 20])).toMatchObject({
        mode: "free",
        k: 2,
        afterId: false,
        pushedIds: [],
    });
});

test("Г3c: week scale, half-day cells: over two adjacent wagons the arrow is at their border, the place opens, the drop goes after A", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "12:00"),
        wo(2, "WO B", 1, "12:00", "17:00"),
        {
            ...wo(4, "WO X", 2, "08:00", "09:00"),
            date_start: "2026-10-06 08:00:00",
            date_finished: "2026-10-06 09:00:00",
        },
    ];
    mockCrewServer();
    await mountGanttView({
        // В 18 мащабът е от default_scale, а периодът — от default_start/stop_date.
        arch: ARCH.replace('default_scale="day"', 'default_scale="week"').replace(
            "{'day': 'hour:quarter'}",
            "{'day': 'hour:quarter', 'week': 'day:half'}"
        ),
        resModel: "mrp.workorder",
        context: { default_start_date: "2026-10-05", default_stop_date: "2026-10-11" },
    });
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    const a = getPillWrapper("WO A").getBoundingClientRect();
    expect(Math.round(getPillWrapper("WO B").getBoundingClientRect().left)).toBe(Math.round(a.right));

    const { moveTo, drop } = await dragPill("WO X");
    // Седмицата: клетката е ден с две части; B е втората (следобедът).
    await moveTo({ pill: "WO B", part: 2 });
    expect(".o_drag_hover").toHaveClass("o_crew_drop_insert");
    expect(".o_crew_drop_arrow").toHaveCount(1);
    expect(queryFirst(".o_crew_drop_arrow").dataset.afterId).toBe("1");
    // Стрелката е на границата A|B (десният край на A; dragPill скролира,
    // затова A се мери наново).
    const aNow = getPillWrapper("WO A").getBoundingClientRect();
    expect(
        Math.abs(queryFirst(".o_crew_drop_arrow").getBoundingClientRect().left + 1 - aNow.right)
    ).toBeLessThan(2);
    // Мястото се разтваря: B е отместена, A — не.
    expect(getPillWrapper("WO B")).toHaveClass("o_crew_drop_open");
    expect(getPillWrapper("WO A")).not.toHaveClass("o_crew_drop_open");
    expect(getPillWrapper("WO B").getBoundingClientRect().left).toBeGreaterThan(aNow.right + 1);
    await drop();
    expect(".o_crew_drop_arrow").toHaveCount(0);
    expect(".o_crew_drop_open").toHaveCount(0);
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 4,
                workcenter_id: 1,
                lane: 1,
                after_workorder_id: 1,
                date_start: false,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г3f: over a slower machine the ghost stretches, back over its own it shrinks", async () => {
    // 19.0.1.9.0 (Росен 12.10.2026): X е 60 мин на Line 1 и 120 на Line 2.
    Workcenter._records = [
        { id: 1, name: "Line 1" },
        { id: 2, name: "Line 2" },
    ];
    Workorder._records = [
        wo(1, "WO A", 1, "12:00", "13:00"),
        { ...wo(2, "WO B", 1, "14:00", "15:00"), workcenter_id: 2 },
        { ...wo(4, "WO X", 2, "08:00", "09:00"), crew_center_durations: { 1: 60, 2: 120 } },
    ];
    mockCrewServer({ lanes: { 1: 2, 2: 1 } });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    const span = () => {
        const [from, to] = /c(\d+) \/ c(\d+)/.exec(queryFirst(".o_drag_hover").style.gridColumn).slice(1);
        return Number(to) - Number(from);
    };
    const own = /c(\d+) \/ c(\d+)/.exec(getPillWrapper("WO X").style.gridColumn).slice(1);
    const ownSpan = Number(own[1]) - Number(own[0]);
    const { moveTo, cancel } = await dragPill("WO X");
    await moveTo({ pill: "WO B" });
    expect(span()).toBe(2 * ownSpan);
    await moveTo({ pill: "WO A" });
    expect(span()).toBe(ownSpan);
    await cancel();
    await expect.waitForSteps(["crew_lane_release"]);
});

test("Г3d: with a gap after A the arrow is on the end of A (where X goes), not on B", async () => {
    // 19.0.1.6.1: X 1 ч, призракът 09:00–10:00 застъпва B (09:30) → след A;
    // X ще почне в 09:00 — стрелката е на края на A, не на началото на B.
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(2, "WO B", 1, "09:30", "10:30"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);

    const { moveTo, drop } = await dragPill("WO X");
    await moveTo({ column: `9 ${DAY}`, row: "Lane 1", part: 1 });
    expect(".o_drag_hover").toHaveClass("o_crew_drop_insert");
    expect(queryFirst(".o_crew_drop_arrow").dataset.afterId).toBe("1");
    const aRight = getPillWrapper("WO A").getBoundingClientRect().right;
    expect(
        Math.abs(queryFirst(".o_crew_drop_arrow").getBoundingClientRect().left + 1 - aRight)
    ).toBeLessThan(2);
    expect(getPillWrapper("WO B")).toHaveClass("o_crew_drop_open");
    await drop();
    await expect.waitForSteps([
        [
            "crew_drop",
            { id: 4, workcenter_id: 1, lane: 1, after_workorder_id: 1, date_start: false },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г3e: a drop in an empty place sticks to the previous wagon: snap arrow, crew_drop with snap", async () => {
    // Р32, Росен 09.10: пуснато далеч след A — стрелката (пунктир) е на
    // края на A, там ще залепне; мястото не се разтваря; сървърът залепва.
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);

    const { moveTo, drop } = await dragPill("WO X");
    await moveTo({ column: `11 ${DAY}`, row: "Lane 1", part: 1 });
    expect(".o_drag_hover").toHaveClass("o_crew_drop_snap");
    expect(".o_drag_hover").not.toHaveClass("o_crew_drop_insert");
    expect(".o_crew_drop_arrow").toHaveClass("o_crew_drop_arrow_snap");
    const aRight = getPillWrapper("WO A").getBoundingClientRect().right;
    expect(
        Math.abs(queryFirst(".o_crew_drop_arrow").getBoundingClientRect().left + 1 - aRight)
    ).toBeLessThan(2);
    expect(".o_crew_drop_open").toHaveCount(0);
    await drop();
    expect(".o_crew_drop_arrow").toHaveCount(0);
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 4,
                workcenter_id: 1,
                lane: 1,
                after_workorder_id: false,
                date_start: "2026-10-05 11:00:00",
                snap: true,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г3: dragging between two wagons shows the arrow; the drop calls crew_drop with after, not write", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(2, "WO B", 1, "09:00", "10:00"),
        wo(3, "WO C", 1, "10:00", "11:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);

    const { moveTo, drop } = await dragPill("WO X");
    await moveTo({ column: `9 ${DAY}`, row: "Lane 1", part: 2 });
    expect(".o_crew_drop_arrow").toHaveCount(1);
    expect(".o_drag_hover").toHaveClass("o_crew_drop_insert");
    expect(queryFirst(".o_crew_drop_arrow").dataset.afterId).toBe("1");
    await drop();
    expect(".o_crew_drop_arrow").toHaveCount(0);
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 4,
                workcenter_id: 1,
                lane: 1,
                after_workorder_id: 1,
                date_start: false,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г3b: a chain that reaches a started wagon is refused on the client", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(2, "WO S", 1, "09:00", "10:00", { state: "progress" }),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    // Започнатата не се влачи (С11).
    expect(getPillWrapper("WO S")).toHaveClass("o_undraggable");

    const { moveTo, drop } = await dragPill("WO X");
    await moveTo({ column: `8 ${DAY}`, row: "Lane 1", part: 3 });
    expect(".o_drag_hover").toHaveClass("o_crew_drop_forbidden");
    await drop();
    await animationFrame();
    await expect.waitForSteps(["crew_lane_release", "get_gantt_data", "crew_train_preview"]);
    expect(".o_notification").toHaveCount(1);
});

test("Г4: resize writes with the crew_gantt_drag flag", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    await resizePill(getPillWrapper("WO A"), "end", 1);
    await expect.waitForSteps([
        ["write", { date_finished: "2026-10-05 10:00:00" }, true],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г5: a drop asks no consent; a dependency conflict blinks after the refresh", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    const server = mockCrewServer();
    server.drop = (call) => {
        // Сървърът мести X; наследникът на друг център не се мести и двете
        // са в конфликт (Р33 изменено) — новото четене носи флага.
        MockServer.env["mrp.workorder"].write([call.id], {
            crew_lane: call.lane,
            date_start: call.date_start,
            date_finished: "2026-10-05 11:00:00",
            crew_dep_conflict: true,
        });
        return {
            status: "done",
            batch_id: 7,
            moves: [],
            notes: ["WO Dep now starts before WO X ends."],
        };
    };
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(".o_gantt_pill.o_crew_dep_conflict").toHaveCount(0);

    const { drop } = await dragPill("WO X");
    await drop({ column: `10 ${DAY}`, row: "Lane 1", part: 1 });
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 4,
                workcenter_id: 1,
                lane: 1,
                after_workorder_id: false,
                date_start: "2026-10-05 10:00:00",
                snap: true,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
    await animationFrame();
    // Без диалог за съгласие; Undo към партидата `drop` (С7).
    expect(".modal").toHaveCount(0);
    expect(".o_notification button:contains(Undo)").toHaveCount(1);
    expect(queryFirst(".o_gantt_pill:contains(WO X)")).toHaveClass("o_crew_dep_conflict");
    expect(queryFirst(".o_gantt_pill:contains(WO A)")).not.toHaveClass("o_crew_dep_conflict");
});

test("Г6: Ctrl + drag does not copy", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    await keyDown("Control");
    const { drop } = await dragPill("WO A");
    await drop({ column: `10 ${DAY}`, row: "Lane 2", part: 1 });
    await keyUp("Control");
    // Без "copy": всяка излишна стъпка счупва проверката.
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 1,
                workcenter_id: 1,
                lane: 2,
                after_workorder_id: false,
                date_start: "2026-10-05 10:00:00",
                snap: true,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
});

test("Г7: the live train moves the wagon on screen without write; during a drag it waits", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "06:00", "07:00"),
        wo(4, "WO X", 2, "09:00", "10:00"),
    ];
    const server = mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(getPillWrapper("WO A").style.gridColumn).toMatch(/^c25 /);

    // Влакът: незапочнатата в миналото тръгва „сега“ (07:01).
    server.preview = () => ({
        1: {
            date_start: "2026-10-05 07:01:00",
            date_finished: "2026-10-05 08:01:00",
            stretch_hours: 0,
            overstretched: false,
            dep_alert: false,
        },
    });
    await advanceTime(60000);
    await expect.waitForSteps(["crew_train_preview"]);
    await animationFrame();
    expect(getPillWrapper("WO A").style.gridColumn).toMatch(/^c29 /);
    expect(".o_gantt_pill.o_crew_trained").toHaveCount(1);

    // По време на влачене проекцията се отлага (Г8) и после се прави.
    const { moveTo, cancel } = await dragPill("WO X");
    await moveTo({ column: `11 ${DAY}`, row: "Lane 2", part: 1 });
    await advanceTime(60000);
    await animationFrame();
    expect.verifySteps([]);
    await cancel();
    await expect.waitForSteps(["crew_lane_release", "crew_train_preview"]);
});

test("Г8: a work order blinks by the projection and by the field", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "06:00", "07:00", { state: "progress", crew_is_overstretched: true }),
        wo(2, "WO B", 2, "06:00", "07:00", { state: "progress" }),
        wo(3, "WO C", 2, "08:00", "09:00"),
    ];
    mockCrewServer({
        preview: () => ({
            2: {
                date_start: "2026-10-05 06:00:00",
                date_finished: "2026-10-05 07:00:00",
                stretch_hours: 3,
                overstretched: true,
                dep_alert: false,
            },
        }),
    });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(queryFirst(".o_gantt_pill:contains(WO A)")).toHaveClass("o_crew_overstretch");
    expect(queryFirst(".o_gantt_pill:contains(WO B)")).toHaveClass("o_crew_overstretch");
    expect(queryFirst(".o_gantt_pill:contains(WO C)")).not.toHaveClass("o_crew_overstretch");
});

test("Г8b: a dependency conflict blinks by the field and by the projection", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00", { crew_dep_conflict: true }),
        wo(2, "WO B", 2, "08:00", "09:00"),
        wo(3, "WO C", 2, "10:00", "11:00"),
    ];
    mockCrewServer({
        preview: () => ({
            2: {
                date_start: "2026-10-05 08:00:00",
                date_finished: "2026-10-05 09:00:00",
                stretch_hours: 0,
                overstretched: false,
                dep_alert: true,
            },
        }),
    });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(queryFirst(".o_gantt_pill:contains(WO A)")).toHaveClass("o_crew_dep_conflict");
    expect(queryFirst(".o_gantt_pill:contains(WO B)")).toHaveClass("o_crew_dep_conflict");
    expect(queryFirst(".o_gantt_pill:contains(WO C)")).not.toHaveClass("o_crew_dep_conflict");
});

test("Г9: the now line is in the column of the mocked date", async () => {
    Workorder._records = [wo(1, "WO A", 1, "10:00", "11:00")];
    mockCrewServer();
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(".o_crew_now_line").toHaveCount(1);
    // 07:00 → колона 1 + 7 × 4 = 29, в началото на подколоната.
    expect(queryFirst(".o_crew_now_line").dataset.col).toBe("29");
    expect(queryFirst(".o_crew_now_line").getAttribute("style")).toMatch(/grid-column:c29\/c30/);
    expect(queryFirst(".o_crew_now_line").getAttribute("style")).toMatch(/left:0\.0\d\d%/);
});

// Г9b (сгъната колона) е само за 19: в 18 Гантът не сгъва неработните колони.
test("Г10: bus — a foreign drag locks the lane, the own tab is ignored, changed refreshes with debounce, the lock expires", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    // waitForChannels пуска всички таймери (и тика на влака): проекцията не
    // се брои тук, а часовете са спрямо часовника на Hoot.
    mockCrewServer({ stepPreview: false });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data"]);
    await waitForChannels(["mrp_crew_lane"]);
    const bus = MockServer.env["bus.bus"];
    // В 18 мокът доставя само до каналите на влезлия потребител
    // (authenticated_user_sid), а тестът не минава през вход.
    MockServer.env.cookie.set("authenticated_user_sid", MockServer.env.uid);
    const drag = (tab) => ({
        workorder_id: 1,
        user_id: 99,
        user_name: "Other User",
        tab,
        source: [1, 1],
        target: [1, 1],
        after_id: false,
        date_start: "2026-10-05 10:00:00",
        date_finished: "2026-10-05 11:00:00",
        source_locked: true,
        target_locked: true,
        expires_at: nowString(60),
    });

    // Собственият раздел се пропуска.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/drag", drag("my-tab"));
    await runAllTimersOnce();
    await animationFrame();
    expect(".o_crew_lane_lock").toHaveCount(0);
    // И вагонът не свети като местен от друг (филтърът по `tab` е и в
    // рендерера, не само в ключалките на модела — ПГ3).
    expect(queryFirst(".o_gantt_pill:contains(WO A)")).not.toHaveClass("o_crew_remote_moving");

    // Чуждото влачене: катинар, readonly клетки, незахващаеми вагони.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/drag", drag("other-tab"));
    await waitFor(".o_crew_lane_lock");
    expect(".o_crew_lane_lock").toHaveCount(1);
    expect(queryFirst(".o_crew_lane_lock").getAttribute("title")).toBe("Other User is moving WO A");
    expect(getCell(`10 ${DAY}`, "Lane 1")).toHaveClass("o_gantt_readonly");
    expect(getCell(`10 ${DAY}`, "Lane 2")).not.toHaveClass("o_gantt_readonly");
    expect(getPillWrapper("WO A")).toHaveClass("o_undraggable");
    expect(queryFirst(".o_gantt_pill:contains(WO A)")).toHaveClass("o_crew_remote_moving");

    // changed → get_gantt_data след 500 ms.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/changed", {
        workcenter_ids: [1],
        workorder_ids: [1],
        source: "drop",
    });
    await runAllTimersOnce();
    await advanceTime(100);
    expect.verifySteps([]);
    await advanceTime(500);
    await expect.waitForSteps(["get_gantt_data"]);
    await animationFrame();
    // Ключалките идват наново от сървъра (мокът връща []).
    expect(".o_crew_lane_lock").toHaveCount(0);

    // Изтичане без `released`: локалният таймер маха катинара.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/drag", drag("other-tab"));
    await waitFor(".o_crew_lane_lock");
    await advanceTime(61000);
    await animationFrame();
    expect(".o_crew_lane_lock").toHaveCount(0);
    expect(getCell(`10 ${DAY}`, "Lane 1")).not.toHaveClass("o_gantt_readonly");
});

test("Г10b: bus — changed is deferred while dragging; released unlocks", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer({ stepPreview: false });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data"]);
    await waitForChannels(["mrp_crew_lane"]);
    const bus = MockServer.env["bus.bus"];
    // В 18 мокът доставя само до каналите на влезлия потребител
    // (authenticated_user_sid), а тестът не минава през вход.
    MockServer.env.cookie.set("authenticated_user_sid", MockServer.env.uid);
    const { moveTo, cancel } = await dragPill("WO X");
    await moveTo({ column: `11 ${DAY}`, row: "Lane 2", part: 1 });
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/changed", {
        workcenter_ids: [1],
        workorder_ids: [1],
        source: "train",
    });
    await runAllTimersOnce();
    await advanceTime(1000);
    await animationFrame();
    expect.verifySteps([]);
    await cancel();
    await expect.waitForSteps(["crew_lane_release", "get_gantt_data"]);

    bus._sendone("mrp_crew_lane", "mrp_crew_lane/locked", {
        workcenter_id: 1,
        lane: 2,
        workorder_id: 4,
        user_id: 99,
        user_name: "Other User",
        tab: "other-tab",
        expires_at: nowString(60),
    });
    await waitFor(".o_crew_lane_lock");
    expect(getCell(`10 ${DAY}`, "Lane 2")).toHaveClass("o_gantt_readonly");
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/released", {
        workcenter_id: 1,
        lane: 2,
        user_id: 99,
        user_name: "Other User",
        tab: "other-tab",
    });
    await runAllTimersOnce();
    expect(".o_crew_lane_lock").toHaveCount(0);
});

test("Г10c: bus — a foreign drag locks only the lanes its user holds, not a refused target", async () => {
    Workorder._records = [
        wo(1, "WO A", 1, "08:00", "09:00"),
        wo(4, "WO X", 2, "08:00", "09:00"),
    ];
    mockCrewServer({ stepPreview: false });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data"]);
    await waitForChannels(["mrp_crew_lane"]);
    const bus = MockServer.env["bus.bus"];
    // В 18 мокът доставя само до каналите на влезлия потребител
    // (authenticated_user_sid), а тестът не минава през вход.
    MockServer.env.cookie.set("authenticated_user_sid", MockServer.env.uid);
    // Другият влачи WO X от писта 2 (държи я) над писта 1, която сървърът
    // му е отказал: писта 1 е на законния си държател и не се заключва.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/drag", {
        workorder_id: 4,
        user_id: 99,
        user_name: "Other User",
        tab: "other-tab",
        source: [1, 2],
        target: [1, 1],
        after_id: 1,
        date_start: "2026-10-05 09:00:00",
        date_finished: "2026-10-05 10:00:00",
        source_locked: true,
        target_locked: false,
        expires_at: nowString(60),
    });
    await waitFor(".o_crew_lane_lock");
    expect(".o_crew_lane_lock").toHaveCount(1);
    expect(getCell(`10 ${DAY}`, "Lane 2")).toHaveClass("o_gantt_readonly");
    expect(getCell(`10 ${DAY}`, "Lane 1")).not.toHaveClass("o_gantt_readonly");
    expect(getPillWrapper("WO A")).not.toHaveClass("o_undraggable");

    // Влачене без нито една хваната писта: нищо не се заключва.
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/released", {
        workcenter_id: 1,
        lane: 2,
        user_id: 99,
        user_name: "Other User",
        tab: "other-tab",
    });
    await runAllTimersOnce();
    expect(".o_crew_lane_lock").toHaveCount(0);
    bus._sendone("mrp_crew_lane", "mrp_crew_lane/drag", {
        workorder_id: 4,
        user_id: 99,
        user_name: "Other User",
        tab: "other-tab",
        source: [1, 1],
        target: [1, 1],
        after_id: false,
        date_start: "2026-10-05 10:00:00",
        date_finished: "2026-10-05 11:00:00",
        source_locked: false,
        target_locked: false,
        expires_at: nowString(60),
    });
    await waitFor(".o_gantt_pill.o_crew_remote_moving");
    expect(".o_crew_lane_lock").toHaveCount(0);
    expect(getCell(`10 ${DAY}`, "Lane 1")).not.toHaveClass("o_gantt_readonly");
    expect(getCell(`10 ${DAY}`, "Lane 2")).not.toHaveClass("o_gantt_readonly");
});

/** Шината стига до клиента асинхронно: няколко кадъра и малко време. */
async function runAllTimersOnce() {
    await animationFrame();
    await advanceTime(10);
    await animationFrame();
}

test("Г14: Undo after a drop, then Recompute: the old notification closes, one Undo stays", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer();
    mockService("action", {
        doAction(action, options = {}) {
            expect.step(["report", action.res_id]);
            options.onClose?.();
            return Promise.resolve(true);
        },
    });
    onRpc("mrp.workcenter.roster", "action_crew_recompute", () => ({
        type: "ir.actions.act_window",
        res_model: "mrp.workcenter.replan.batch",
        res_id: 9,
        views: [[false, "form"]],
        target: "new",
    }));
    await mountGanttView({
        arch: ARCH,
        resModel: "mrp.workorder",
        context: {
            crew_workcenter_id: 1,
            default_start_date: "2026-10-05",
            default_stop_date: "2026-10-05",
        },
    });
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    const { drop } = await dragPill("WO A");
    await drop({ column: `10 ${DAY}`, row: "Lane 2", part: 1 });
    await expect.waitForSteps([
        [
            "crew_drop",
            {
                id: 1,
                workcenter_id: 1,
                lane: 2,
                after_workorder_id: false,
                date_start: "2026-10-05 10:00:00",
                snap: true,
            },
        ],
        "get_gantt_data",
        "crew_train_preview",
    ]);
    await animationFrame();
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("Work order moved.");

    await queryFirst(".o_crew_gantt_button_recompute").click();
    await expect.waitForSteps([["report", 9], "get_gantt_data", "crew_train_preview"]);
    await animationFrame();
    await animationFrame();
    // Едно известие — новото; старото (на пускането) е затворено.
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText("Plan recomputed.");
});

// №142: само работното време.

/** Шаблонът на колоните на решетката на клетките. */
function colsTemplate() {
    return queryFirst(".o_gantt_renderer").style.getPropertyValue("--Gantt__GridColumns-grid-template-columns");
}

const NIGHTS = [
    { start: "2026-10-05 00:00:00", stop: "2026-10-05 06:00:00" },
    { start: "2026-10-05 18:00:00", stop: "2026-10-06 00:00:00" },
];

test("№142: crewCovered, crewHiddenCols and crewColsTemplate", () => {
    const t = (hour) => luxon.DateTime.fromISO(`2026-10-05T${String(hour).padStart(2, "0")}:00:00`);
    const sub = (col, from, to) => ({ col, start: t(from), stop: t(to).minus({ seconds: 1 }) });
    const night = [{ start: t(0), stop: t(6) }];
    expect(crewCovered(night, t(1), t(2))).toBe(true);
    expect(crewCovered(night, t(5), t(7))).toBe(false);
    // Два интервала един след друг покриват подколоната заедно.
    expect(crewCovered([{ start: t(0), stop: t(1) }, { start: t(1), stop: t(3) }], t(0), t(3))).toBe(true);
    const subs = [sub(1, 1, 2), sub(2, 7, 8), sub(3, 5, 6)];
    // Общата ос: скрито е само неработното за ВСИЧКИ центрове.
    expect([...crewHiddenCols(subs, [night])]).toEqual([1, 3]);
    expect([...crewHiddenCols(subs, [night, [{ start: t(0), stop: t(2) }]])]).toEqual([1]);
    // Център без неработно време не скрива нищо.
    expect([...crewHiddenCols(subs, [night, []])]).toEqual([]);
    expect(crewColsTemplate([1, 3, 5, 6], new Set([3, 4]), 10)).toBe(
        "[c1]minmax(20px,1fr)[c3]0px[c5]minmax(10px,1fr)[c6]"
    );
});

test("№142: the nights of the center are hidden by default; the button shows them again", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer({ unavailable: NIGHTS });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(".o_gantt_renderer").toHaveClass("o_crew_off_time_hidden");
    expect(colsTemplate()).toInclude("0px");
    expect(".o_crew_gantt_button_off_time").toHaveText("Show Non-Working Time");

    await contains(".o_crew_gantt_button_off_time").click();
    await expect.waitForSteps([["crew_gantt_set_show_off_time", true], "get_gantt_data", "crew_train_preview"]);
    expect(".o_gantt_renderer").not.toHaveClass("o_crew_off_time_hidden");
    expect(colsTemplate()).not.toInclude("0px");
    expect(".o_crew_gantt_button_off_time").toHaveText("Hide Non-Working Time");
});

test("№142: a center without non-working time hides nothing", async () => {
    Workorder._records = [wo(1, "WO A", 1, "08:00", "09:00")];
    mockCrewServer({ unavailable: [] });
    await mountCrewGantt();
    expect.verifySteps(["get_gantt_data", "crew_train_preview"]);
    expect(".o_gantt_renderer").not.toHaveClass("o_crew_off_time_hidden");
    expect(colsTemplate()).not.toInclude("0px");
});
