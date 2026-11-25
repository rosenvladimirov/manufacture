import { deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { GanttModel } from "@web_gantt/gantt_model";

/** Контекстният флаг на влаченето (M16); сървърът го проверява в `write`. */
export const CREW_GANTT_DRAG = "crew_gantt_drag";
/** Полето на пистата (Р29) — групирането център → писта. */
export const CREW_LANE_FIELD = "crew_lane";
/** Моделът на ключалката на пистата (Р38, M20). */
export const CREW_LOCK_MODEL = "mrp.workcenter.lane.lock";

/** Ключът на пистата в картите на ключалките: "<център>:<писта>". */
export function crewLaneKey(workcenterId, lane) {
    return `${workcenterId}:${lane}`;
}

/**
 * Моделът на Ганта „Планирай център“ (TECH_DESIGN §4 и §9.4).
 *
 * - екипът (`employee_assigned_ids`) идва САМО от наряда: влаченето между
 *   редовете по служител не бива да го заменя, затова се изрязва от
 *   данните на графика;
 * - resize/влачене извън пистите пише с флага `crew_gantt_drag` в
 *   контекста на `write` (M16). Флагът не живее в контекста на действието;
 * - при групиране по `crew_lane` (Р29): празните писти се добавят на
 *   клиента (Г2), редовете на пистите взимат неработното време на центъра
 *   (Г3), а влакът на живо идва от `crew_train_preview` (M22, С8) — само
 *   на екрана, нищо не се пише в базата (Р36).
 */
export class CrewGanttModel extends GanttModel {
    setup() {
        super.setup(...arguments);
        // В 18 няма _processGanttData (от 19): _fetchData разглобява отговора
        // на get_gantt_data и губи нашите ключове. Отговорът се прихваща тук
        // и се обработва в _fetchDataPostProcess.
        const orm = this.orm;
        this.crewGanttData = {};
        this.orm = Object.create(orm, {
            call: {
                value: async (model, method, ...rest) => {
                    const result = await orm.call(model, method, ...rest);
                    if (method === "get_gantt_data") {
                        this.crewGanttData = result || {};
                    }
                    return result;
                },
            },
        });
        /** Ключалките на ДРУГИТЕ: "<център>:<писта>" → ключалка (М20, Р38). */
        this.crewLocks = new Map();
        /** Проекцията на влака по поръчка: id → {trained, overstretched, depAlert}. */
        this.crewTrain = {};
        /** Датите от базата на поръчките, които проекцията е преместила. */
        this.crewOriginalDates = {};
        /** Разликата сървър − браузър в ms (часовникът е един — сървърният). */
        this.crewServerOffset = 0;
        /** Разделът (tab) на този Гант — своите съобщения по шината се пропускат. */
        this.crewTab = `crew_${Date.now().toString(36)}_${Math.random()
            .toString(36)
            .slice(2, 8)}`;
        /** Затварянето на текущото известие с Undo (общо за контролера и рендерера). */
        this.crewCloseUndo = null;
        /** №142: потребителят е пуснал неработното време обратно (от сървъра). */
        this.crewShowOffTime = false;
    }

    /**
     * №142: превключвателят „неработното време“ — изборът е на потребителя
     * (пише се на сървъра), после Гантът се зарежда наново.
     */
    async crewSetShowOffTime(show) {
        await this.orm.call("res.users", "crew_gantt_set_show_off_time", [Boolean(show)]);
        this.crewShowOffTime = Boolean(show);
        await this.fetchData();
    }

    /** Пистите са включени, когато групирането съдържа `crew_lane`. */
    get crewActive() {
        return Boolean(this.metaData.groupedBy?.includes(CREW_LANE_FIELD));
    }

    /** „Сега“ по часовника на сървъра (ms). */
    crewNowMs() {
        return Date.now() + this.crewServerOffset;
    }

    //-------------------------------------------------------------------------
    // Стандартни куки
    //-------------------------------------------------------------------------

    /**
     * @override
     */
    _scheduleToData(schedule) {
        const data = super._scheduleToData(schedule);
        delete data.employee_assigned_ids;
        return data;
    }

    /**
     * @override
     */
    async _reschedule(ids, data, context) {
        return super._reschedule(ids, data, { ...context, [CREW_GANTT_DRAG]: true });
    }

    /**
     * Г2, Г3, M21: празните писти, етикетите „Lane N“, неработното време на
     * центъра по редовете на пистите, ключалките и часовникът на сървъра.
     *
     * @override
     */
    _processGanttData(metaData, data, ganttData) {
        super._processGanttData?.(...arguments);
        this.crewShowOffTime = Boolean(ganttData.crew_show_off_time);
        if (!metaData.groupedBy.includes(CREW_LANE_FIELD)) {
            return;
        }
        data.crewLanes = ganttData.crew_lanes || {};
        data.crewNames = ganttData.crew_names_label || {};
        if (ganttData.server_now) {
            this.crewServerOffset = deserializeDateTime(ganttData.server_now).toMillis() - Date.now();
        }
        this.crewLocks = new Map();
        for (const lock of ganttData.crew_locks || []) {
            this.crewSetLock(lock);
        }
        this._crewProcessRows(data.rows, data.crewLanes, data.crewNames);
        this.crewTrain = {};
        this.crewOriginalDates = {};
    }

    /**
     * Обхожда редовете: под всеки ред на център сверява пистите с броя от
     * сървъра (`crew_lanes`), добавя липсващите и слага етикетите и
     * родителя за неработното време.
     */
    _crewProcessRows(rows, lanes, crewNames = {}) {
        for (const row of rows || []) {
            // №146 на Теолино: бригадата на центъра в етикета му — имената,
            // ако е една и съща в целия период, иначе „различни бригади“.
            // Обработката минава по едни и същи редове повече от веднъж —
            // етикетът се гради от запазеното име, не се долепва пак.
            if (row.groupedByField === "workcenter_id" && row.resId) {
                const names = crewNames[row.resId] ?? crewNames[String(row.resId)];
                row.crewBaseName ??= row.name;
                row.name = names ? `${row.crewBaseName} · ${names}` : row.crewBaseName;
            }
            if (!row.rows) {
                continue;
            }
            const laneRows = row.rows.filter((sub) => sub.groupedByField === CREW_LANE_FIELD);
            if (row.groupedByField === "workcenter_id" && row.resId && laneRows.length) {
                const count = Number(lanes[row.resId] ?? lanes[String(row.resId)] ?? 0);
                const present = new Set(laneRows.map((sub) => sub.resId));
                const parentGroup = JSON.parse(row.id);
                for (let lane = 1; lane <= count; lane++) {
                    if (present.has(lane)) {
                        continue;
                    }
                    row.rows.push({
                        consolidate: false,
                        fromServer: false,
                        groupedBy: laneRows[0].groupedBy,
                        groupedByField: CREW_LANE_FIELD,
                        groupLevel: laneRows[0].groupLevel,
                        id: JSON.stringify([...parentGroup, { [CREW_LANE_FIELD]: lane }]),
                        name: "",
                        recordIds: [],
                        resId: lane,
                    });
                }
                row.rows.sort((a, b) => (a.resId || 0) - (b.resId || 0));
                for (const sub of row.rows) {
                    if (sub.groupedByField === CREW_LANE_FIELD && sub.resId) {
                        sub.name = _t("Lane %s", sub.resId);
                        sub.parentGroupedField = "workcenter_id";
                        sub.parentResId = row.resId;
                    }
                }
            } else {
                for (const sub of laneRows) {
                    if (sub.resId) {
                        sub.name = _t("Lane %s", sub.resId);
                    }
                }
            }
            this._crewProcessRows(row.rows, lanes, crewNames);
        }
    }

    /**
     * Проекцията на влака веднага след всяко зареждане (§9.4): същите
     * данни, нищо не се пише.
     *
     * @override
     */
    async _fetchDataPostProcess(metaData, data) {
        await super._fetchDataPostProcess(...arguments);
        this._processGanttData(metaData, data, this.crewGanttData);
    }

    async _fetchData(metaData, additionalContext) {
        await super._fetchData(...arguments);
        if (this.crewActive) {
            try {
                const result = await this.crewTrainPreview();
                this.crewApplyTrain(result);
            } catch {
                // Проекцията е само подсказка на екрана: грешката не спира Ганта.
            }
        }
    }

    //-------------------------------------------------------------------------
    // Ключалките (Р38, M20)
    //-------------------------------------------------------------------------

    /**
     * Записва чужда ключалка; своите (същият раздел) не се пазят — те не
     * заключват собствения Гант.
     *
     * @returns {boolean} дали картата се е сменила
     */
    crewSetLock(lock) {
        if (!lock || lock.tab === this.crewTab) {
            return false;
        }
        const expires = lock.expires_at
            ? deserializeDateTime(lock.expires_at).toMillis()
            : this.crewNowMs() + 60000;
        this.crewLocks.set(crewLaneKey(lock.workcenter_id, lock.lane), {
            workcenterId: lock.workcenter_id,
            lane: lock.lane,
            userId: lock.user_id,
            userName: lock.user_name || "",
            workorderId: lock.workorder_id || false,
            tab: lock.tab || false,
            expires,
        });
        return true;
    }

    /** Маха ключалката на пистата (при `released` от същия потребител). */
    crewDropLock(workcenterId, lane, userId) {
        const key = crewLaneKey(workcenterId, lane);
        const lock = this.crewLocks.get(key);
        if (lock && (!userId || lock.userId === userId)) {
            this.crewLocks.delete(key);
            return true;
        }
        return false;
    }

    /** Маха изтеклите ключалки (локалният таймер, без `released`). */
    crewPurgeExpiredLocks() {
        const now = this.crewNowMs();
        let changed = false;
        for (const [key, lock] of this.crewLocks) {
            if (lock.expires <= now) {
                this.crewLocks.delete(key);
                changed = true;
            }
        }
        return changed;
    }

    /** Активната чужда ключалка на пистата или null. */
    crewLockFor(workcenterId, lane) {
        const lock = this.crewLocks.get(crewLaneKey(workcenterId, lane));
        if (!lock || lock.expires <= this.crewNowMs()) {
            return null;
        }
        return lock;
    }

    crewLaneAcquire(workcenterId, lane, workorderId) {
        return this.orm.silent.call(CREW_LOCK_MODEL, "crew_lane_acquire", [], {
            workcenter_id: workcenterId,
            lane,
            workorder_id: workorderId,
            tab: this.crewTab,
        });
    }

    crewLanePing(params) {
        return this.orm.silent.call(CREW_LOCK_MODEL, "crew_lane_ping", [], {
            ...params,
            tab: this.crewTab,
        });
    }

    crewLaneRelease() {
        return this.orm.silent.call(CREW_LOCK_MODEL, "crew_lane_release", [], {
            tab: this.crewTab,
        });
    }

    //-------------------------------------------------------------------------
    // „Пусни тук“ (M17) и влакът (M22)
    //-------------------------------------------------------------------------

    /**
     * M17: един метод за вмъкване, свободно пускане, друга писта и друга
     * машина (С6). Отказът на сървъра е `UserError` — стандартният диалог.
     */
    crewDrop(workorderId, params) {
        const { context } = this.searchParams;
        return this.mutex.exec(() =>
            this.orm.call("mrp.workorder", "crew_drop", [[workorderId]], {
                workcenter_id: params.workcenter_id,
                lane: params.lane,
                after_workorder_id: params.after_workorder_id || false,
                date_start: params.date_start || false,
                // Р32 (09.10): само при пускане в празно място.
                ...(params.snap ? { snap: true } : {}),
                context,
            })
        );
    }

    /** M22: проекцията на влака към СЕГА за заредените поръчки (само четене). */
    async crewTrainPreview() {
        const ids = (this.data.records || []).map((record) => record.id);
        if (!ids.length || this.orm.isSample) {
            return null;
        }
        return this.orm.silent.call("mrp.workorder", "crew_train_preview", [ids], {
            context: this.searchParams.context,
        });
    }

    /**
     * Пише проектираните дати в `this.data.records` (само на екрана) и
     * пази знаците на проекцията в `crewTrain`. Полета извън изгледа НЕ се
     * добавят към записите (декорациите обхождат полетата им).
     *
     * @returns {boolean} дали нещо се е сменило
     */
    crewApplyTrain(result) {
        if (!result) {
            return false;
        }
        const { dateStartField, dateStopField } = this.metaData;
        if (result.server_now) {
            this.crewServerOffset = deserializeDateTime(result.server_now).toMillis() - Date.now();
        }
        const projected = result.records || {};
        let changed = false;
        const train = {};
        for (const record of this.data.records || []) {
            const original = this.crewOriginalDates[record.id];
            const item = projected[record.id] || projected[String(record.id)];
            if (!item) {
                if (original) {
                    record[dateStartField] = original.start;
                    record[dateStopField] = original.stop;
                    delete this.crewOriginalDates[record.id];
                    changed = true;
                }
                continue;
            }
            const base = original || { start: record[dateStartField], stop: record[dateStopField] };
            const start = item.date_start ? deserializeDateTime(item.date_start) : base.start;
            const stop = item.date_finished ? deserializeDateTime(item.date_finished) : base.stop;
            const trained = Boolean(
                (start && base.start && +start !== +base.start) ||
                    (stop && base.stop && +stop !== +base.stop)
            );
            if (trained) {
                this.crewOriginalDates[record.id] = base;
                if (+record[dateStartField] !== +start || +record[dateStopField] !== +stop) {
                    record[dateStartField] = start;
                    record[dateStopField] = stop;
                    changed = true;
                }
            } else if (original) {
                record[dateStartField] = original.start;
                record[dateStopField] = original.stop;
                delete this.crewOriginalDates[record.id];
                changed = true;
            }
            train[record.id] = {
                trained,
                overstretched: Boolean(item.overstretched),
                depAlert: Boolean(item.dep_alert),
                stretchHours: item.stretch_hours || 0,
            };
        }
        if (JSON.stringify(train) !== JSON.stringify(this.crewTrain)) {
            changed = true;
        }
        this.crewTrain = train;
        return changed;
    }
}
