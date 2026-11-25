/** „Смяна/Бригада“ и „Групи“: старт/стоп върху поръчка — хората на ИЗБРАНАТА бригада/група. */
import { patch } from "@web/core/utils/patch";
import { MrpDisplayRecord } from "@mrp_workorder/mrp_display/mrp_display_record";
import { crewShiftState } from "./crew_shift_state";

patch(MrpDisplayRecord.prototype, {
    async startWorking(shouldStop = false) {
        const { resModel, resId } = this.props.record;
        // „Смяна/Бригада“ и „Групи“ — хората на избраната бригада/група
        if (!["crew", "group"].includes(crewShiftState.mode) || resModel !== "mrp.workorder") {
            return super.startWorking(...arguments);
        }
        await this.props.updateEmployees();
        const ownerId = this.props.sessionOwner.id;
        // 18: x2many-ът няма resIds — по записите
        const working = this.props.record.data.employee_ids.records.some((e) => e.resId === ownerId);
        if (!working) {
            await this.model.orm.call(resModel, "crew_shift_start", [resId]);
        } else if (shouldStop) {
            await this.model.orm.call(resModel, "crew_shift_stop", [resId]);
        } else {
            return this.props.updateEmployees();
        }
        await this.env.reload(this.props.production);
        if (crewShiftState.refresh) {
            await crewShiftState.refresh();
        }
        return this.props.updateEmployees();
    },
});
