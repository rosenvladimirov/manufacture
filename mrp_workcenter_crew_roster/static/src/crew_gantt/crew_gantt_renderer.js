import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDateTime, formatDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { KeepLast } from "@web/core/utils/concurrency";
import { MRPWorkorderGanttRenderer } from "@mrp_workorder/mrp_workorder_gantt_renderer";
import { dateAddFixedOffset, diffColumn, getCellsOnRow } from "@web_gantt/gantt_helpers";
import { CREW_CHANGED_DEBOUNCE, CrewDeferredCall, useCrewGanttBus } from "./crew_gantt_bus";
import { CREW_LANE_FIELD, crewLaneKey } from "./crew_gantt_model";
import { computeInsertion } from "./crew_lane_insert";
import { crewNotifyUndo } from "./crew_undo";
import { crewColsTemplate, crewHiddenCols } from "./crew_off_time";

const { DateTime } = luxon;

/** Тикът на влака и на линията „сега“ (ms), подравнен на минута. */
export const CREW_TICK = 60000;
/** При месец/година проекцията е на всеки 5 тика (§9.4). */
export const CREW_SLOW_TICKS = 5;
/** Ping-ът на ключалката: най-много 4 пъти в секунда (С5). */
export const CREW_PING_MIN_INTERVAL = 250;
/** Heartbeat на ключалката по време на влачене (С5). */
export const CREW_HEARTBEAT = 20000;

/**
 * Рендерерът на Ганта „Планирай център“ (TECH_DESIGN §4, §9.4).
 *
 * Стандартният Гант на поръчките, плюс (само при групиране по `crew_lane`):
 * - стрелката „пусни тук“ между два вагона и пускането през `crew_drop`
 *   (M17) вместо `write` (Р32, Р33, С6);
 * - диалогът за съгласие при зависими на друг център и Undo към партидата;
 * - влакът на живо (`crew_train_preview`, M22), линията „сега“ и мигането
 *   на разтегнатите (Р34, Р36, Р37);
 * - застъпване в пистата (Р30 на екрана);
 * - ключалките и шината (Р38).
 * Сборните стойности се смятат и за редовете по служител (изгледът
 * „Work Orders by Employee“). Ctrl (копиране) е изключен (Г5, С16).
 *
 * Важно (Г8): id-тата на вагоните се правят наново при всяко
 * `computeDerivedParams`, затова по време на влачене нищо не презарежда
 * данните — влакът, `changed` и ключалките се отлагат до края му.
 */
export class CrewGanttRenderer extends MRPWorkorderGanttRenderer {
    static template = "mrp_workcenter_crew_roster.CrewGanttRenderer";
    static rowHeaderTemplate = "mrp_workcenter_crew_roster.CrewGanttRenderer.RowHeader";

    setup() {
        // Полетата трябват още в super.setup() (onInteractionChange се вика там).
        /** Редовете на пистите със застъпване (Р30 на екрана). */
        this.crewConflictRows = new Set();
        /** id на реда → {workcenterId, lane}. */
        this.crewRowKeys = {};
        /** Текущото влачене (ключалка, ping, „пуснато“). */
        this.crewDragSession = null;
        /** Решението „пусни тук“ при влачене — НЕ е реактивно (Г8). */
        this.crewDrop = null;
        /** Чуждите влачения: id на поръчката → {userId, userName, afterId, expires}. */
        this.crewRemote = new Map();
        this.crewTrainPending = false;
        this.crewLocksDirty = false;
        this.crewTickCount = 0;
        /** №142: подколоните, неработни за всички показани центрове (нулева ширина). */
        this.crewHidden = new Set();
        this.crewChanged = new CrewDeferredCall(
            () => this.model.fetchData(),
            CREW_CHANGED_DEBOUNCE,
            () => this.crewIsBusy
        );
        super.setup();
        // №142: виртуалната решетка (кои колони да рисува при скрол) получава
        // истинската ширина на колоната — без скритите ѝ подколони.
        const setColumnsWidths = this.virtualGrid.setColumnsWidths.bind(this.virtualGrid);
        this.virtualGrid.setColumnsWidths = (widths) =>
            setColumnsWidths(this.crewHidden.size ? this.crewColumnWidths() : widths);
        this.crewClock = useState({ nowTs: Date.now() });
        this.crewTrainKeepLast = new KeepLast();
        useCrewGanttBus(this);
        onMounted(() => this.crewStartClock());
        onWillUnmount(() => this.crewStopClock());
    }

    //-------------------------------------------------------------------------
    // Състояние
    //-------------------------------------------------------------------------

    /** Пистите са включени при групиране по `crew_lane`. */
    get crewActive() {
        return Boolean(this.model.crewActive);
    }

    /** Влачене или resize: данните не се сменят (Г8). */
    get crewIsBusy() {
        return (
            Boolean(this.crewDragSession) ||
            ["drag", "resize"].includes(this.interaction?.mode)
        );
    }

    get crewConflictTitle() {
        return _t("Overlapping work orders in this lane");
    }

    /** Пистата на поръчката {workcenterId, lane} или null. */
    crewRecordLane(record) {
        // В 18 many2one в записа на Ганта е [id, име] (в 19 — {id, display_name}).
        const workcenter = record.workcenter_id;
        const workcenterId = Array.isArray(workcenter) ? workcenter[0] : workcenter?.id;
        return workcenterId ? { workcenterId, lane: record[CREW_LANE_FIELD] || 1 } : null;
    }

    /**
     * Колко пъти поръчката е по-дълга на центъра `workcenterId`, отколкото на
     * своя (19.0.1.9.0, Росен 12.10.2026: картинката се разпъва и свива по
     * машината под нея). 1 — на своя център или когато не се знае.
     */
    crewStretch(record, workcenterId) {
        const durations = record.crew_center_durations || {};
        // В 18 many2one в записа на Ганта е [id, име] (в 19 — {id, display_name}).
        const workcenter = record.workcenter_id;
        const own = durations[Array.isArray(workcenter) ? workcenter[0] : workcenter?.id];
        const other = durations[workcenterId];
        return own > 0 && other > 0 ? other / own : 1;
    }

    /** Пистата на реда от групирането (център → писта) или null. */
    crewParseRow(rowId) {
        if (!rowId) {
            return null;
        }
        if (this.crewRowKeys[rowId]) {
            return this.crewRowKeys[rowId];
        }
        try {
            const group = Object.assign({}, ...JSON.parse(rowId));
            const workcenter = group.workcenter_id;
            const lane = group[CREW_LANE_FIELD];
            if (Array.isArray(workcenter) && workcenter[0] && lane) {
                return { workcenterId: workcenter[0], lane };
            }
        } catch {
            // Не е ред на писта.
        }
        return null;
    }

    /** Чуждата ключалка на реда на пистата или null. */
    crewRowLock(row) {
        const key = this.crewActive && this.crewRowKeys[row.id];
        return key ? this.model.crewLockFor(key.workcenterId, key.lane) : null;
    }

    crewRowLockTitle(row) {
        const lock = this.crewRowLock(row);
        if (!lock) {
            return "";
        }
        const record = (this.model.data.records || []).find((r) => r.id === lock.workorderId);
        const workorder = record ? record.display_name : lock.workorderId ? `#${lock.workorderId}` : _t("a work order");
        return _t("%(user)s is moving %(wo)s", { user: lock.userName, wo: workorder });
    }

    /** Поръчките, които някой друг мести в момента. */
    crewRemoteMovingIds() {
        const ids = new Set(this.crewRemote.keys());
        for (const lock of this.model.crewLocks?.values() || []) {
            if (lock.workorderId) {
                ids.add(lock.workorderId);
            }
        }
        return ids;
    }

    //-------------------------------------------------------------------------
    // Override-и на стандартния рендерер
    //-------------------------------------------------------------------------

    /**
     * @override
     */
    computeDerivedParams() {
        this.crewConflictRows = new Set();
        this.crewRowKeys = {};
        this.crewRemoteMoving = this.crewRemoteMovingIds();
        this.crewRemoteAfter = new Set(
            [...this.crewRemote.values()].map((item) => item.afterId).filter(Boolean)
        );
        const result = super.computeDerivedParams(...arguments);
        this.crewHidden = this.crewComputeHidden();
        this.crewScheduleLockExpiry();
        return result;
    }

    //-------------------------------------------------------------------------
    // №142: само работното време
    //-------------------------------------------------------------------------

    /** id-тата на показаните центрове (редовете по `workcenter_id`, на всяко ниво). */
    crewDisplayedWorkcenterIds(rows = this.model.data.rows, ids = new Set()) {
        for (const row of rows || []) {
            if (row.groupedByField === "workcenter_id" && row.resId) {
                ids.add(row.resId);
            }
            // `|| []`: листът няма `rows`, а `undefined` би върнал подразбирането (всички редове).
            this.crewDisplayedWorkcenterIds(row.rows || [], ids);
        }
        return ids;
    }

    /**
     * Скритите подколони: само в Ганта с писти, когато потребителят не е
     * пуснал неработното време; център без неработно време не скрива нищо.
     */
    crewComputeHidden() {
        if (!this.crewActive || this.model.crewShowOffTime) {
            return new Set();
        }
        const ids = this.crewDisplayedWorkcenterIds();
        if (!ids.size) {
            return new Set();
        }
        const byWorkcenter = this.model.data.unavailabilities?.workcenter_id || {};
        const lists = [...ids].map((id) => byWorkcenter[id] || []);
        const { cellPart } = this.model.metaData.scale;
        const subColumns = [];
        for (let col = 1; col <= this.columnCount * cellPart; col++) {
            subColumns.push({ col, ...this.getSubColumnFromColNumber(col) });
        }
        return crewHiddenCols(subColumns, lists);
    }

    /** Ширините на колоните без скритите подколони (за виртуалната решетка). */
    crewColumnWidths() {
        const { cellPart } = this.model.metaData.scale;
        const widths = [];
        for (let j = 0; j < this.columnCount; j++) {
            let visible = 0;
            for (let i = 1; i <= cellPart; i++) {
                if (!this.crewHidden.has(j * cellPart + i)) {
                    visible++;
                }
            }
            widths.push(visible * this.cellPartWidth);
        }
        return widths;
    }

    /**
     * Ширината на подколона се смята по ВИДИМИТЕ подколони: освободеното от
     * неработното време място отива за работното.
     *
     * @override
     */
    computeSomeWidths() {
        super.computeSomeWidths(...arguments);
        if (!this.crewHidden.size) {
            return;
        }
        const { cellPart, minimalColumnWidth } = this.model.metaData.scale;
        const visible = this.columnCount * cellPart - this.crewHidden.size;
        const minimal = Math.max(1, Math.floor(minimalColumnWidth / cellPart));
        this.cellPartWidth = Math.max(minimal, Math.floor(this.cellContainerWidth / Math.max(1, visible)));
        this.columnWidth = this.cellPartWidth * cellPart;
        const needed = this.cellPartWidth * visible;
        this.totalWidth = needed > this.cellContainerWidth ? this.rowHeaderWidth + needed : null;
    }

    /**
     * Скритите участъци са отделни участъци на решетката с нулева ширина.
     *
     * @override
     */
    computeColsTemplate() {
        if (!this.crewHidden.size) {
            return super.computeColsTemplate(...arguments);
        }
        return crewColsTemplate(this.getColInCoarseGridKeys(), this.crewHidden, this.cellPartWidth);
    }

    /**
     * Р30 на екрана: застъпване в пистата → `crewConflictRows`.
     *
     * @override
     */
    processRow(row, pills, processAsGroup = true) {
        const result = super.processRow(...arguments);
        if (row.groupedByField === CREW_LANE_FIELD && row.parentResId && row.resId) {
            const processed = result.rows[0];
            this.crewRowKeys[processed.id] = { workcenterId: row.parentResId, lane: row.resId };
            if (this.crewHasOverlap(this.rowPills[processed.id] || [])) {
                this.crewConflictRows.add(processed.id);
            }
        }
        return result;
    }

    /**
     * Застъпване по реалните часове (не по клетките, които закръглят);
     * двойка от две започнати не е нарушение (В3).
     */
    crewHasOverlap(rowPills) {
        const { dateStartField, dateStopField } = this.model.metaData;
        const items = rowPills
            // Непланираната (дългосрочният план) не е вагон — стои на датите
            // на МО-то и се застъпва по замисъл.
            .filter((pill) => pill.record && !pill.record.crew_is_unplanned)
            .map((pill) => ({
                start: +pill.record[dateStartField],
                stop: +pill.record[dateStopField],
                started: pill.record.state === "progress",
            }))
            .sort((a, b) => a.start - b.start);
        for (let i = 0; i < items.length; i++) {
            for (let j = i + 1; j < items.length && items[j].start < items[i].stop; j++) {
                if (!(items[i].started && items[j].started)) {
                    return true;
                }
            }
        }
        return false;
    }

    /**
     * С11: започнатата не се влачи и не се мести началото ѝ (десният край
     * остава разтеглив, M14.5). Заключената от друг писта — нищо (Р38).
     *
     * @override
     */
    getPill(record) {
        const pill = super.getPill(record);
        if (record.state === "progress") {
            pill.disableDrag = true;
            pill.disableStartResize = true;
        }
        if (this.crewActive) {
            const lane = this.crewRecordLane(record);
            if (lane && this.model.crewLockFor(lane.workcenterId, lane.lane)) {
                pill.disableDrag = true;
                pill.disableStartResize = true;
                pill.disableStopResize = true;
            }
        }
        return pill;
    }

    /**
     * Мигането на разтегнатите (Р37) и на конфликтите по зависимост (Р33
     * изменено, 1.5.5: полето `crew_dep_conflict` или проекцията на влака),
     * влакът и чуждите влачения.
     *
     * @override
     */
    enrichPill(pill) {
        super.enrichPill(pill);
        const { record } = pill;
        const train = this.model.crewTrain?.[record.id];
        const classes = [];
        if (train?.overstretched || record.crew_is_overstretched) {
            classes.push("o_crew_overstretch");
        }
        if (train?.trained) {
            classes.push("o_crew_trained");
        }
        if (train?.depAlert || record.crew_dep_conflict) {
            classes.push("o_crew_dep_conflict");
        }
        if (this.crewRemoteMoving?.has(record.id)) {
            classes.push("o_crew_remote_moving");
        }
        if (this.crewRemoteAfter?.has(record.id)) {
            classes.push("o_crew_remote_after");
        }
        if (record.crew_is_unplanned) {
            classes.push("o_crew_unplanned");
        }
        if (classes.length) {
            pill.className = [pill.className, ...classes].filter(Boolean).join(" ");
        }
        return pill;
    }

    /**
     * Общият ред на EE (`mrp_workorder_gantt_renderer.js` `addTo`) чете
     * твърдо `date_start`/`date_finished`. Дългосрочният план (Росен
     * 14.10.2026) е върху „началото/края в плана“, а непланираната поръчка
     * няма `date_start` — без това Гантът пада при отваряне. Подаваме
     * датите на изгледа; в групата остава истинската лента.
     *
     * @override
     */
    addTo(pill, group) {
        const { dateStartField, dateStopField } = this.model.metaData;
        if (dateStartField === "date_start" && dateStopField === "date_finished") {
            return super.addTo(pill, group);
        }
        const record = {
            ...pill.record,
            date_start: pill.record[dateStartField],
            date_finished: pill.record[dateStopField],
        };
        const before = group.pills.length;
        const added = super.addTo({ ...pill, record }, group);
        if (added && group.pills.length > before) {
            group.pills[group.pills.length - 1] = pill;
        }
        return added;
    }

    /**
     * @override
     */
    ganttCellAttClass(row, column) {
        const classes = super.ganttCellAttClass(row, column);
        if (this.crewConflictRows.has(row.id)) {
            classes.o_crew_lane_conflict = true;
        }
        if (this.crewRowLock(row)) {
            classes.o_gantt_readonly = true;
        }
        return classes;
    }

    /**
     * Колоната на линията „сега“ влиза в грубата мрежа (Г9).
     *
     * @override
     */
    computeVisibleColumns() {
        super.computeVisibleColumns();
        // №142: границите между видимо и скрито стават граници на участъци.
        if (this.crewHidden.size) {
            const { cellPart } = this.model.metaData.scale;
            const [first, last] = this.virtualGrid.columnsIndexes;
            for (let col = first * cellPart + 1; col <= (last + 1) * cellPart + 1; col++) {
                if (this.crewHidden.has(col) !== this.crewHidden.has(col - 1)) {
                    this.coarseGridCols[col] = true;
                }
            }
        }
        const position = this.crewNowPosition();
        if (position) {
            this.coarseGridCols[position.column[0]] = true;
            this.coarseGridCols[position.column[1]] = true;
        }
    }

    /**
     * @override
     */
    shouldComputeAggregateValues(row) {
        return (
            super.shouldComputeAggregateValues(row) ||
            row.groupedByField === "employee_assigned_ids"
        );
    }

    /**
     * Ctrl не включва копирането (Г5, С16): копие на поръчка от Ганта не се
     * прави.
     *
     * @override
     */
    onWindowKeyDown(ev) {
        if (ev.key === "Control") {
            return;
        }
        super.onWindowKeyDown(ev);
    }

    /**
     * @override
     */
    onWindowKeyUp(ev) {
        if (ev.key === "Control") {
            return;
        }
        super.onWindowKeyUp(ev);
    }

    //-------------------------------------------------------------------------
    // Линията „сега“ и влакът на живо (Р34, Р36, С8)
    //-------------------------------------------------------------------------

    /** „Сега“ по часовника на сървъра. */
    crewNow() {
        return DateTime.fromMillis(this.crewClock.nowTs + (this.model.crewServerOffset || 0));
    }

    /**
     * Мястото на линията „сега“: подколоната и отместването в проценти; на
     * сгъната колона — на сгъвката.
     */
    crewNowPosition() {
        const { globalStart, globalStop, scale } = this.model.metaData;
        if (!globalStart || !globalStop || !this.columns?.length || !this.crewClock) {
            return null;
        }
        const now = this.crewNow();
        if (now < globalStart || now >= globalStop) {
            return null;
        }
        const column = this.columns.find((c) => c.start <= now && now <= c.stop);
        if (!column) {
            return null;
        }
        if (column.isFolded) {
            return { column: [...column.grid.column], left: 50, folded: true, now };
        }
        const { cellPart, interval } = scale;
        const { column: columnStart, delta } = this.getSubColumnFromDate(now);
        const col = 1 + diffColumn(globalStart, columnStart, interval) * cellPart + delta;
        const subColumn = this.getSubColumnFromColNumber(col);
        const span = subColumn.stop.plus({ seconds: 1 }) - subColumn.start;
        const left = span > 0 ? Math.min(100, Math.max(0, ((now - subColumn.start) / span) * 100)) : 0;
        return { column: [col, col + 1], left, folded: false, now };
    }

    /** За шаблона: стилът и заглавието на линията „сега“. */
    crewNowLine() {
        const position = this.crewNowPosition();
        if (!position) {
            return null;
        }
        return {
            folded: position.folded,
            col: position.column[0],
            style: `${this.getGridPosition({ column: position.column })};grid-row:1/-1;left:${position.left.toFixed(3)}%`,
            title: _t("Now: %s", formatDateTime(position.now)),
        };
    }

    crewStartClock() {
        const delay = CREW_TICK - (Date.now() % CREW_TICK) || CREW_TICK;
        this.crewClockTimeout = browser.setTimeout(() => {
            this.crewTick();
            this.crewClockInterval = browser.setInterval(() => this.crewTick(), CREW_TICK);
        }, delay);
    }

    crewStopClock() {
        browser.clearTimeout(this.crewClockTimeout);
        browser.clearInterval(this.crewClockInterval);
        browser.clearTimeout(this.crewLockTimeout);
        this.crewChanged.cancel();
        const session = this.crewDragSession;
        if (session) {
            browser.clearInterval(session.heartbeat);
            browser.clearTimeout(session.pingTimeout);
        }
    }

    /** Тикът: линията, после проекцията (ден/седмица всеки път, месец/година на 5). */
    crewTick() {
        if (document.hidden) {
            return;
        }
        this.crewTickCount++;
        this.crewClock.nowTs = Date.now();
        if (!this.crewActive) {
            return;
        }
        const scaleId = this.model.metaData.scale?.id;
        const every = ["day", "week"].includes(scaleId) ? 1 : CREW_SLOW_TICKS;
        if (this.crewTickCount % every === 0) {
            this.crewRefreshTrain();
        }
    }

    /**
     * Проекцията на влака (M22). По време на влачене не се вика — пази се
     * за след пускането (Г8). Нищо не се пише в базата (Р36).
     */
    async crewRefreshTrain() {
        if (this.crewIsBusy) {
            this.crewTrainPending = true;
            return;
        }
        let result;
        try {
            result = await this.crewTrainKeepLast.add(this.model.crewTrainPreview());
        } catch {
            return;
        }
        if (this.crewIsBusy) {
            this.crewTrainPending = true;
            return;
        }
        if (this.model.crewApplyTrain(result)) {
            this.model.notify();
        }
    }

    /** Отложеното по време на влачене/resize: влак, `changed`, ключалки. */
    crewAfterBusy() {
        if (this.crewIsBusy) {
            return;
        }
        if (this.crewTrainPending) {
            this.crewTrainPending = false;
            this.crewRefreshTrain();
        }
        this.crewChanged.flush();
        if (this.crewLocksDirty) {
            this.crewLocksDirty = false;
            this.model.notify();
        }
    }

    //-------------------------------------------------------------------------
    // Влаченето: ключалка, стрелка, ping (Р32, Р38)
    //-------------------------------------------------------------------------

    /**
     * @override
     */
    onInteractionChange() {
        super.onInteractionChange();
        const { mode } = this.interaction;
        if (!this.crewActive) {
            return;
        }
        if (mode === "drag" && !this.crewDragSession) {
            this.crewStartDrag();
        } else if (mode === null) {
            if (this.crewDragSession) {
                this.crewEndDrag();
            }
            this.crewAfterBusy();
        }
    }

    /** Началото на влачене: хваща пистата на източника (M20.1). */
    crewStartDrag() {
        const pill = this.pills[this.stickyPillId];
        if (!pill?.record) {
            return;
        }
        const { record } = pill;
        const source = this.crewRecordLane(record);
        const session = {
            recordId: record.id,
            source,
            dropped: false,
            refused: null,
            targetLocked: null,
            targetHolder: "",
            lastKey: null,
            lastPing: 0,
            pingTimeout: null,
            pingParams: null,
            heartbeat: null,
        };
        this.crewDragSession = session;
        if (!source) {
            return;
        }
        session.pingParams = {
            workcenter_id: source.workcenterId,
            lane: source.lane,
            workorder_id: record.id,
        };
        this.model
            .crewLaneAcquire(source.workcenterId, source.lane, record.id)
            .then((result) => {
                if (result && !result.ok) {
                    session.refused = result;
                }
            })
            .catch(() => {});
        session.heartbeat = browser.setInterval(() => this.crewPing(session), CREW_HEARTBEAT);
    }

    /**
     * Краят на влачене (след `onDrop`, Г4): неупуснатото освобождава
     * ключалките си (M20.4); пуснатото — освобождава ги M17 на сървъра.
     */
    crewEndDrag() {
        const session = this.crewDragSession;
        this.crewDragSession = null;
        this.crewDrop = null;
        this.crewClearArrow();
        browser.clearInterval(session.heartbeat);
        browser.clearTimeout(session.pingTimeout);
        if (!session.dropped && session.source) {
            this.model.crewLaneRelease().catch(() => {});
        }
    }

    /**
     * Стрелката: при влачене се смята решението и се рисува между вагоните.
     * В 18 влаченето на пила няма onDrag (updateBadges е от 19), но при всяка
     * смяна на клетка/част вика addStickyCoordinates → този метод. Призракът
     * се закача след него, затова решението е в следващия кадър.
     *
     * @override
     */
    setSomeGridStyleProperties() {
        super.setSomeGridStyleProperties(...arguments);
        if (this.interaction?.mode === "drag" && this.crewDragSession) {
            browser.requestAnimationFrame(() => {
                if (this.interaction.mode === "drag" && this.crewDragSession) {
                    this.crewOnDrag();
                }
            });
        }
    }

    crewOnDrag() {
        const session = this.crewDragSession;
        const ghost = this.gridRef.el?.querySelector(".o_drag_hover");
        const cell = this.cellForDrag.el;
        const pill = this.pills[this.stickyPillId];
        const match = ghost && /c(\d+)/.exec(ghost.style.gridColumn || "");
        if (!ghost || !cell || !pill?.record || !match) {
            this.crewDrop = null;
            this.crewClearArrow();
            return;
        }
        const diff = Number(match[1]) - pill.grid.column[0];
        const decision = this.crewComputeDrop(cell.dataset.rowId, pill, diff);
        this.crewDrop = decision;
        // Призракът — с дължината на поръчката на машината под него
        // (19.0.1.9.0); EE го задава само при смяна на клетката.
        if (decision?.grid) {
            ghost.style.gridColumn = `c${decision.grid[0]} / c${decision.grid[1]}`;
        }
        ghost.classList.toggle(
            "o_crew_drop_insert",
            Boolean(decision && decision.mode === "insert" && !decision.forbidden)
        );
        ghost.classList.toggle("o_crew_drop_forbidden", Boolean(!decision || decision.forbidden));
        // Р32 (09.10): празно място — призракът залепва за предходната.
        ghost.classList.toggle(
            "o_crew_drop_snap",
            Boolean(decision && decision.mode === "free" && !decision.forbidden)
        );
        this.crewDrawArrow(decision, ghost);
        if (decision && session) {
            this.crewSchedulePing(session, decision);
        }
    }

    /**
     * Решението „пусни тук“ за реда `rowId`, когато влаченият вагон `pill` е
     * отместен с `diff` клетки: пистата, `computeInsertion` и ключалката на
     * целта. Застъпването и мястото се смятат по колоните на екрана
     * (призракът срещу вагоните, 19.0.1.6.1), часовете — за пускането.
     */
    crewComputeDrop(rowId, pill, diff) {
        const target = this.crewParseRow(rowId);
        if (!target) {
            return null;
        }
        const { record } = pill;
        const { dateStartField, dateStopField, scale } = this.model.metaData;
        const { cellTime, time, cellPart } = scale;
        const start = dateAddFixedOffset(record[dateStartField], { [time]: cellTime * (diff || 0) });
        // 19.0.1.9.0 (Росен 12.10.2026): на друга машина поръчката е толкова
        // по-дълга или по-къса, колкото е по-бавна или по-бърза машината.
        const stretch = this.crewStretch(record, target.workcenterId);
        const duration = (record[dateStopField] - record[dateStartField]) * stretch;
        let grid = null;
        if (pill.grid?.column) {
            const [first, last] = pill.grid.column;
            const from = first + (diff || 0);
            const span = Math.max(1, Math.round((last - first) * stretch));
            grid = [from, Math.min(from + span, this.columnCount * cellPart + 1)];
        }
        const seen = new Set();
        const wagons = [];
        for (const rowPill of this.rowPills[rowId] || []) {
            const other = rowPill.record;
            if (!other || other.id === record.id || seen.has(other.id) || other.crew_is_unplanned) {
                continue;
            }
            seen.add(other.id);
            wagons.push({
                id: other.id,
                start: +other[dateStartField],
                stop: +other[dateStopField],
                started: other.state === "progress",
                col: rowPill.grid?.column,
            });
        }
        const useGrid = Boolean(grid) && wagons.every((wagon) => wagon.col);
        const insertion = computeInsertion(wagons, +start, duration, useGrid ? grid : null);
        const lock = this.model.crewLockFor(target.workcenterId, target.lane);
        const targetLocked =
            this.crewDragSession?.targetLocked === crewLaneKey(target.workcenterId, target.lane);
        return {
            ...target,
            ...insertion,
            rowId,
            start,
            duration,
            grid,
            stretch,
            lock,
            locked: Boolean(lock || targetLocked),
            forbidden: insertion.blocked || Boolean(lock || targetLocked),
        };
    }

    /** Обвивката (DOM) на вагона `recordId` в реда `rowId` или null. */
    crewWagonWrapper(rowId, recordId) {
        const rowPill = (this.rowPills[rowId] || []).find((p) => p.record?.id === recordId);
        return (rowPill && this.getPillWrapperEl(rowPill.id)) || null;
    }

    /**
     * Стрелката е `div.o_crew_drop_arrow` в контейнера на клетките, в пиксели:
     * на десния край на вагон k-1 (границата), а при k = 0 — на левия край на
     * първия. После мястото „се разтваря“ (`crewOpenPlace`).
     *
     * 19.0.1.6.1 (Р32, Росен 09.10): при пускане в празно място (`free`)
     * стрелката е на десния край на предходната поръчка — там ще залепне
     * (`o_crew_drop_arrow_snap`); без предходна — без стрелка (от сега).
     */
    crewDrawArrow(decision, ghost = null) {
        this.crewClearArrow();
        if (!decision || (decision.mode !== "insert" && decision.mode !== "free")) {
            return;
        }
        const { wagons, k, rowId } = decision;
        const snap = decision.mode === "free";
        if (snap && (k === 0 || decision.forbidden)) {
            return;
        }
        let wrapper = k > 0 ? this.crewWagonWrapper(rowId, wagons[k - 1].id) : null;
        let atRight = Boolean(wrapper);
        if (!wrapper && wagons[k] && !snap) {
            wrapper = this.crewWagonWrapper(rowId, wagons[k].id);
            atRight = false;
        }
        const container = this.cellContainerRef.el;
        if (!wrapper || !container) {
            return;
        }
        if (!this.crewArrowEl) {
            this.crewArrowEl = document.createElement("div");
        }
        const arrow = this.crewArrowEl;
        arrow.className = decision.forbidden
            ? "o_crew_drop_arrow o_crew_drop_arrow_forbidden"
            : snap
              ? "o_crew_drop_arrow o_crew_drop_arrow_snap"
              : "o_crew_drop_arrow";
        const containerRect = container.getBoundingClientRect();
        const rect = wrapper.getBoundingClientRect();
        arrow.style.left = `${(atRight ? rect.right : rect.left) - containerRect.left}px`;
        arrow.style.top = `${rect.top - containerRect.top}px`;
        arrow.style.height = `${rect.height}px`;
        arrow.dataset.afterId = decision.afterId || "";
        if (arrow.parentElement !== container) {
            container.append(arrow);
        }
        if (!decision.forbidden && !snap) {
            this.crewOpenPlace(decision, ghost);
        }
    }

    /**
     * „Разтваряне“ (Р32 на екрана): избутваните вагони се отместват надясно
     * с ширината на призрака — само CSS (клас + променлива), без запис и без
     * пререндер (Р36, Г8). Махат се при всяко ново решение и в края.
     */
    crewOpenPlace(decision, ghost) {
        const width = ghost?.getBoundingClientRect().width || 0;
        if (!width) {
            return;
        }
        this.crewOpenEls = [];
        for (const recordId of decision.pushedIds || []) {
            const wrapper = this.crewWagonWrapper(decision.rowId, recordId);
            if (wrapper) {
                wrapper.style.setProperty("--o-crew-open-shift", `${width}px`);
                wrapper.classList.add("o_crew_drop_open");
                this.crewOpenEls.push(wrapper);
            }
        }
    }

    crewClearArrow() {
        this.crewArrowEl?.remove();
        for (const wrapper of this.crewOpenEls || []) {
            wrapper.classList.remove("o_crew_drop_open");
            wrapper.style.removeProperty("--o-crew-open-shift");
        }
        this.crewOpenEls = [];
    }

    /** Ping при смяна на (писта, k) — до 4 пъти в секунда (С5). */
    crewSchedulePing(session, decision) {
        if (!session.source) {
            return;
        }
        session.pingParams = {
            workcenter_id: session.source.workcenterId,
            lane: session.source.lane,
            workorder_id: session.recordId,
            target_workcenter_id: decision.workcenterId,
            target_lane: decision.lane,
            after_workorder_id: decision.afterId || false,
            date_start: serializeDateTime(decision.start),
            date_finished: serializeDateTime(decision.start.plus(decision.duration)),
        };
        const key = `${decision.workcenterId}:${decision.lane}:${decision.mode}:${decision.k}`;
        if (key === session.lastKey) {
            return;
        }
        session.lastKey = key;
        browser.clearTimeout(session.pingTimeout);
        const wait = CREW_PING_MIN_INTERVAL - (Date.now() - session.lastPing);
        if (wait <= 0) {
            this.crewPing(session);
        } else {
            session.pingTimeout = browser.setTimeout(() => this.crewPing(session), wait);
        }
    }

    async crewPing(session) {
        const params = session.pingParams;
        if (!params || this.crewDragSession !== session) {
            return;
        }
        session.lastPing = Date.now();
        let result;
        try {
            result = await this.model.crewLanePing(params);
        } catch {
            return;
        }
        const key = crewLaneKey(
            params.target_workcenter_id || params.workcenter_id,
            params.target_lane || params.lane
        );
        if (result && !result.ok) {
            session.targetLocked = key;
            session.targetHolder = result.user || "";
        } else if (session.targetLocked === key) {
            session.targetLocked = null;
        }
    }

    //-------------------------------------------------------------------------
    // Пускането (M17, С6)
    //-------------------------------------------------------------------------

    /**
     * Пускането отива в `crew_drop` без `super` (Г5): нито `write`, нито
     * `copy`, нито стандартното Undo.
     *
     * @override
     */
    async dragPillDrop(params) {
        if (!this.crewActive) {
            return super.dragPillDrop(params);
        }
        const session = this.crewDragSession;
        if (session) {
            // onDrop е преди onDragEnd (Г4): ключалките ги пуска M17 или отказът.
            session.dropped = true;
        }
        // В 18 целевата клетка е `cell` (в 19 — `cellDst`).
        const { pill, cell: cellDst, diff } = params;
        const draggedPill = this.pills[pill.dataset.pillId];
        const { record } = draggedPill;
        const decision = this.crewComputeDrop(cellDst.dataset.rowId, draggedPill, diff);
        this.crewClearArrow();
        const refusal = this.crewDropRefusal(decision, session);
        if (refusal) {
            this.notificationService.add(refusal, { type: "warning" });
            await this.crewReleaseQuietly();
            await this.model.fetchData();
            return;
        }
        await this.crewSubmitDrop(record, decision);
    }

    /** Отказът на клиента преди сървъра (Р32, Р38) или null. */
    crewDropRefusal(decision, session) {
        if (!decision) {
            return _t("Drop the work order in a lane of a work center.");
        }
        const holder =
            decision.lock?.userName ||
            (session?.refused && (session.refused.user || "")) ||
            (decision.locked && session?.targetHolder) ||
            null;
        if (decision.lock || session?.refused || decision.locked) {
            return _t("%(user)s is moving work orders in this lane. Try again in a minute.", {
                user: holder || _t("Another user"),
            });
        }
        if (decision.blocked) {
            return _t("The push would move a started work order; it cannot be dropped here.");
        }
        return null;
    }

    /**
     * M17. 19.0.1.5.5 (Р33 изменено): без диалог за съгласие — зависимите
     * на друг център не се местят, а мигат след опресняването.
     */
    async crewSubmitDrop(record, decision) {
        const sendStart = decision.mode === "free" || decision.k === 0;
        const args = {
            // Р32 (09.10): празно място — сървърът залепва X за предходната.
            ...(decision.mode === "free" ? { snap: true } : {}),
            workcenter_id: decision.workcenterId,
            lane: decision.lane,
            after_workorder_id: decision.afterId || false,
            date_start: sendStart
                ? serializeDateTime(DateTime.fromMillis(decision.dateStart))
                : false,
        };
        let result;
        try {
            result = await this.model.crewDrop(record.id, args);
        } catch (error) {
            // UserError → стандартният диалог; планът се зарежда наново.
            await this.crewReleaseQuietly();
            await this.model.fetchData();
            throw error;
        }
        this.crewShowUndo(result);
        await this.model.fetchData();
    }

    /**
     * Лепкаво известие с Undo към партидата `drop` (С7) — тънка обвивка над
     * общия помощник (`crew_undo.js`, §9.13.4): защита от двоен клик,
     * `fetchData` след Undo. Партидата е току-що създадена, затова без
     * проверката `crew_can_undo`.
     */
    crewShowUndo(result) {
        const notes = result?.notes || [];
        return crewNotifyUndo(
            { model: this.model, orm: this.orm, notification: this.notificationService },
            { batchId: result?.batch_id, message: _t("Work order moved."), notes, check: false }
        );
    }

    /**
     * Затварянето на известието живее в модела (`crewCloseUndo`), общо с
     * контролера: стандартните известия на EE (влачене извън пистите) и
     * нашите Undo се сменят едно с друго, а `onWillUnmount` затваря
     * текущото.
     */
    get closeNotificationFn() {
        return this.model?.crewCloseUndo || null;
    }

    set closeNotificationFn(fn) {
        if (this.model) {
            this.model.crewCloseUndo = fn;
        }
    }

    async crewReleaseQuietly() {
        try {
            await this.model.crewLaneRelease();
        } catch {
            // Ключалката изтича сама след минута.
        }
    }

    //-------------------------------------------------------------------------
    // Шината (Р38, С3–С5)
    //-------------------------------------------------------------------------

    crewIsOwn(payload) {
        return !payload || payload.tab === this.model.crewTab;
    }

    crewOnBusDrag(payload) {
        if (this.crewIsOwn(payload)) {
            return;
        }
        const lockOf = ([workcenterId, lane] = []) =>
            workcenterId && {
                workcenter_id: workcenterId,
                lane,
                user_id: payload.user_id,
                user_name: payload.user_name,
                workorder_id: payload.workorder_id,
                tab: payload.tab,
                expires_at: payload.expires_at,
            };
        // Заключват се само пистите, които влачещият наистина държи (сървърът
        // го казва с `source_locked`/`target_locked`): отказаната цел е на
        // законния си държател и не се заключва за него (Р38, находка 3).
        if (payload.source_locked) {
            this.model.crewSetLock(lockOf(payload.source));
        }
        if (payload.target_locked) {
            this.model.crewSetLock(lockOf(payload.target));
        }
        const expires = payload.expires_at
            ? deserializeDateTime(payload.expires_at).toMillis()
            : this.model.crewNowMs() + 60000;
        this.crewRemote.set(payload.workorder_id, {
            userId: payload.user_id,
            userName: payload.user_name,
            afterId: payload.after_id || false,
            expires,
        });
        this.crewLocksChanged();
    }

    crewOnBusLocked(payload) {
        if (this.crewIsOwn(payload)) {
            return;
        }
        this.model.crewSetLock(payload);
        this.crewLocksChanged();
    }

    crewOnBusReleased(payload) {
        if (this.crewIsOwn(payload)) {
            return;
        }
        this.model.crewDropLock(payload.workcenter_id, payload.lane, payload.user_id);
        for (const [workorderId, item] of this.crewRemote) {
            if (item.userId === payload.user_id) {
                this.crewRemote.delete(workorderId);
            }
        }
        this.crewLocksChanged();
    }

    crewOnBusChanged() {
        if (this.crewActive) {
            this.crewChanged.trigger();
        }
    }

    /**
     * Сменени ключалки: извън влачене — пререндер; по време на влачене само
     * клетките на пистите в DOM стават readonly (Г8), а пререндерът чака.
     */
    crewLocksChanged() {
        this.crewScheduleLockExpiry();
        if (!this.crewActive) {
            return;
        }
        if (this.crewIsBusy) {
            this.crewToggleLockedCells();
            this.crewLocksDirty = true;
            return;
        }
        this.model.notify();
    }

    crewToggleLockedCells() {
        if (!this.gridRef.el) {
            return;
        }
        for (const [rowId, key] of Object.entries(this.crewRowKeys)) {
            const locked = Boolean(this.model.crewLockFor(key.workcenterId, key.lane));
            for (const cell of getCellsOnRow(this.gridRef.el, rowId)) {
                cell.classList.toggle("o_gantt_readonly", locked);
            }
        }
    }

    /** Локален таймер: маха ключалките при `expires_at` и без `released`. */
    crewScheduleLockExpiry() {
        browser.clearTimeout(this.crewLockTimeout);
        let next = Infinity;
        for (const lock of this.model.crewLocks?.values() || []) {
            next = Math.min(next, lock.expires);
        }
        for (const item of this.crewRemote.values()) {
            next = Math.min(next, item.expires);
        }
        if (next === Infinity) {
            return;
        }
        const delay = Math.max(0, next - this.model.crewNowMs()) + 50;
        this.crewLockTimeout = browser.setTimeout(() => {
            const now = this.model.crewNowMs();
            let changed = this.model.crewPurgeExpiredLocks();
            for (const [workorderId, item] of this.crewRemote) {
                if (item.expires <= now) {
                    this.crewRemote.delete(workorderId);
                    changed = true;
                }
            }
            if (changed) {
                this.crewLocksChanged();
            } else {
                this.crewScheduleLockExpiry();
            }
        }, delay);
    }
}
