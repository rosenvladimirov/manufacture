import { _t } from "@web/core/l10n/translation";

/** Моделът на партидата на препланирането (отчетът и отмяната, M6). */
export const CREW_BATCH_MODEL = "mrp.workcenter.replan.batch";

/**
 * Общото лепкаво известие с Undo към партида (фаза 2, TECH_DESIGN §9.13.4):
 * след пускане със стрелката, след „Recompute“ и след съветника
 * „Rearrange Plan“.
 *
 * - функцията за затваряне живее в МОДЕЛА (`model.crewCloseUndo`), обща за
 *   контролера и рендерера: новото известие затваря старото, за да няма
 *   две Undo към различни партиди;
 * - `check`: първо се чете `crew_can_undo` — човек може да е отменил вече
 *   от формата на отчета, тогава известие няма (иначе второ Undo →
 *   „already undone“). При пускането (`check=false`) партидата е току-що
 *   създадена и проверката е излишна (поведението на Г1/Г3 не се мени);
 * - Undo е защитено от двоен клик (флаг `undoing`), а във `finally`
 *   известието се затваря и Гантът се презарежда;
 * - при `partial` след Undo — предупреждение да се види отчетът.
 *
 * @param {Object} deps `{ model, orm, notification }`
 * @param {Object} params `{ batchId, message, notes, check }`
 * @returns {Promise<boolean>} дали е показано известие
 */
export async function crewNotifyUndo(deps, params) {
    const { model, orm, notification } = deps;
    const { batchId, message, notes = [], check = true } = params;
    crewCloseUndo(model);
    if (!batchId) {
        return false;
    }
    if (check) {
        let canUndo = false;
        try {
            const [batch] = await orm.read(CREW_BATCH_MODEL, [batchId], ["crew_can_undo"]);
            canUndo = Boolean(batch?.crew_can_undo);
        } catch {
            // Партидата не се чете (изтрита, права) — няма какво да се предложи.
            canUndo = false;
        }
        if (!canUndo) {
            return false;
        }
        // Докато се чете, може да е дошло друго известие — то е по-новото.
        crewCloseUndo(model);
    }
    const text = notes.length ? `${message}\n${notes.join("\n")}` : message;
    let undoing = false;
    const close = notification.add(text, {
        type: "success",
        sticky: true,
        buttons: [
            {
                name: _t("Undo"),
                icon: "fa-undo",
                onClick: async () => {
                    if (undoing) {
                        return;
                    }
                    undoing = true;
                    let state = false;
                    try {
                        await orm.call(CREW_BATCH_MODEL, "action_undo", [[batchId]]);
                        state = await crewReadState(orm, batchId);
                    } finally {
                        close();
                        if (model.crewCloseUndo === close) {
                            model.crewCloseUndo = null;
                        }
                        await model.fetchData();
                    }
                    if (state === "partial") {
                        notification.add(
                            _t("Some work orders could not be returned; see the report."),
                            { type: "warning" }
                        );
                    }
                },
            },
        ],
    });
    model.crewCloseUndo = close;
    return true;
}

/** Затваря текущото известие с Undo (ако има) — общо за Ганта. */
export function crewCloseUndo(model) {
    const close = model.crewCloseUndo;
    model.crewCloseUndo = null;
    close?.();
}

/** Състоянието на партидата след Undo; грешката при четене не пречи. */
async function crewReadState(orm, batchId) {
    try {
        const [batch] = await orm.read(CREW_BATCH_MODEL, [batchId], ["state"]);
        return batch?.state || false;
    } catch {
        return false;
    }
}
