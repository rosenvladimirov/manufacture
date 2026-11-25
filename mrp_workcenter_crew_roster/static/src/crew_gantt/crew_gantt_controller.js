import { serializeDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { GanttController } from "@web_gantt/gantt_controller";
import { CREW_BATCH_MODEL, crewNotifyUndo } from "./crew_undo";

const { DateTime } = luxon;

/** Действието на съветника „Rearrange Plan“ (фаза 2, §9.13.3). */
export const CREW_REPLAN_WIZARD_ACTION =
    "mrp_workcenter_crew_roster.mrp_workcenter_replan_wizard_action";

/**
 * Контролерът на Ганта „Планирай център“:
 * - „Recompute“ (M7) за центъра от контекста `crew_workcenter_id`; без
 *   център в контекста (напр. „Work Orders by Employee“) не се показва;
 * - „Rearrange Plan“ (съветникът, фаза 2) — винаги; центърът се избира в
 *   съветника;
 * - след затварянето на отчета — лепкаво известие с Undo към партидата
 *   (общият помощник `crew_undo.js`).
 */
export class CrewGanttController extends GanttController {
    setup() {
        super.setup();
        this.notification = useService("notification");
        this.crewRecomputeRunning = false;
        this.crewReplanRunning = false;
    }

    /** №142: бутонът „неработното време“ — само в Ганта с писти. */
    async onClickCrewOffTime() {
        await this.model.crewSetShowOffTime(!this.model.crewShowOffTime);
    }

    /** Центърът, избран през „Plan Work Center“ или smart бутона „Plan“. */
    get crewWorkcenterId() {
        return this.props.context?.crew_workcenter_id || false;
    }

    /**
     * Центровете на Ганта за съветника: няколко от „Plan Work Center“
     * (`crew_workcenter_ids`, Р40) или единият (`crew_workcenter_id`).
     */
    get crewWorkcenterIds() {
        const ids = this.props.context?.crew_workcenter_ids;
        if (Array.isArray(ids) && ids.length) {
            return ids;
        }
        return this.crewWorkcenterId ? [this.crewWorkcenterId] : [];
    }

    /**
     * Периодът на Ганта за съветника: началото не е преди днес (обхватът
     * на изгледа почва от предишния период), краят е последният показан ден
     * (`stopDate` е включителен).
     */
    get crewReplanPeriod() {
        const { startDate, stopDate } = this.model.metaData;
        const today = DateTime.local().startOf("day");
        const start = startDate && startDate > today ? startDate : today;
        return {
            crew_date_from: serializeDate(start),
            crew_date_to: stopDate ? serializeDate(stopDate) : false,
        };
    }

    /** Известието с Undo след затварянето на отчета на партидата. */
    crewNotifyUndo(batchId, message) {
        return crewNotifyUndo(
            { model: this.model, orm: this.orm, notification: this.notification },
            { batchId, message }
        );
    }

    /**
     * „Преизчисли“ за центъра: сървърът връща отчета (партидата, `res_id`);
     * след затварянето му Гантът се презарежда и предлага Undo. Контекстът
     * на действието НЕ се разпъва (Ф3) — подава се само центърът.
     */
    async onClickCrewRecompute() {
        if (!this.crewWorkcenterId || this.crewRecomputeRunning) {
            return;
        }
        this.crewRecomputeRunning = true;
        try {
            const action = await this.orm.call(
                "mrp.workcenter.roster",
                "action_crew_recompute",
                // Методът не е @api.model (19.0.1.6.1): първият аргумент са
                // ids — празни, нарядите не се ползват.
                [[]],
                { context: { crew_workcenter_id: this.crewWorkcenterId } }
            );
            const batchId = action?.res_model === CREW_BATCH_MODEL ? action.res_id : false;
            await this.actionService.doAction(action, {
                onClose: async () => {
                    await this.model.fetchData();
                    await this.crewNotifyUndo(batchId, _t("Plan recomputed."));
                },
            });
        } finally {
            this.crewRecomputeRunning = false;
        }
    }

    /**
     * „Rearrange Plan“: съветникът с центъра на Ганта (ако има) и периода
     * на изгледа. Контекстът — САМО ключовете `crew_*` (Ф3, Ф2-2): нито
     * контекстът на действието, нито `default_*`.
     *
     * Съветникът се затваря с `infos.crew_batch_id` (`crew_from_gantt`) и
     * Гантът сам отваря отчета — така знае коя партида да предложи за Undo
     * (X на отчета не носи id). Отчетът се отваря ИЗВЪН `onClose` на
     * съветника: `_removeDialog` на action service чака `onClose` и после
     * нулира текущия диалог — нов диалог, отворен вътре, би останал без
     * собствения си `onClose`.
     */
    async onClickCrewReplan() {
        if (this.crewReplanRunning) {
            return;
        }
        this.crewReplanRunning = true;
        try {
            await this.actionService.doAction(CREW_REPLAN_WIZARD_ACTION, {
                additionalContext: {
                    crew_workcenter_ids: this.crewWorkcenterIds,
                    ...this.crewReplanPeriod,
                    crew_from_gantt: true,
                },
                onClose: (infos) => {
                    this.crewAfterReplan(infos?.crew_batch_id);
                },
            });
        } finally {
            this.crewReplanRunning = false;
        }
    }

    /**
     * След съветника: с партида — отчетът, а след затварянето му известие
     * с Undo; без партида (Cancel/X) — само презареждане.
     */
    async crewAfterReplan(batchId) {
        if (!batchId) {
            await this.model.fetchData();
            return;
        }
        const action = await this.orm.call(CREW_BATCH_MODEL, "action_open_report", [[batchId]]);
        await this.model.fetchData();
        await this.actionService.doAction(action, {
            onClose: async () => {
                await this.model.fetchData();
                await this.crewNotifyUndo(batchId, _t("Plan rearranged."));
            },
        });
    }
}
