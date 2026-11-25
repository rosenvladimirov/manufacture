/** Панелът с хората: „Човеци“ и „Смяна/Бригада“ над списъка; в режим „Смяна/Бригада“ —
 *  бригадите на смяната, „Редактиране на бригади“ и „Изритай“ (Росен 15.10.2026).
 *  18: панелът е един (без offcanvas), долу е „Add Operator“; „Edit Operators“ и неговото
 *  „Да напусне ли всички поръчки?“ ги няма — в 18 човек без поръчки се маха с „×“. */
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { MrpDisplayEmployeesPanel } from "@mrp_workorder/mrp_display/employees_panel";
import { PinPopup } from "@mrp_workorder/components/pin_popup";
import { DialogWrapper } from "@mrp_workorder/components/dialog_wrapper";
import { CrewShiftDialog, CrewShiftGroupDialog, CrewShiftKickDialog } from "./crew_shift_dialog";
import { crewShiftState } from "./crew_shift_state";

MrpDisplayEmployeesPanel.props = {
    ...MrpDisplayEmployeesPanel.props,
    updateEmployees: { type: Function, optional: true },
};

function confirmDialog(dialog, title, body) {
    return new Promise((resolve) => {
        dialog.add(ConfirmationDialog, {
            title,
            body,
            confirmLabel: _t("Yes"),
            cancelLabel: _t("No"),
            confirm: () => resolve(true),
            cancel: () => resolve(false),
        });
    });
}

patch(MrpDisplayEmployeesPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        // useState — панелът се прерисува при всяка промяна на бригадите на смяната
        this.crewShift = useState(crewShiftState);
        crewShiftState.refresh = () => this.refreshCrews();
        onWillStart(async () => {
            crewShiftState.leaders = await this.orm.call("hr.employee", "crew_shift_leaders", []);
            await this.refreshCrews();
        });
    },

    async refreshCrews() {
        const state = await this.orm.call("hr.employee", "crew_shift_state", []);
        crewShiftState.mode = state.mode;
        crewShiftState.crews = state.crews;
        crewShiftState.selected = state.selected;
        crewShiftState.groups = state.groups;
        crewShiftState.groupSelected = state.group_selected;
    },

    async selectGroup(group) {
        await this.orm.call("hr.employee", "crew_shift_select_group", [group.id]);
        await this.reloadAll();
    },

    async editGroups() {
        const leaders = await this.orm.call("hr.employee", "crew_shift_group_leaders", []);
        if (!leaders.length) {
            this.notification.add(_t("There is no crew leader to divide the groups."), { type: "danger" });
            return;
        }
        const people = this.props.employees.connected.map((e) => ({ id: e.id, name: e.name }));
        this.dialog.add(CrewShiftGroupDialog, {
            people,
            groups: crewShiftState.groups,
            leaders,
            onConfirm: (groups, leader) => this.saveGroups(groups, leader),
        });
    },

    async removeGroupFromList(group) {
        const sure = await confirmDialog(
            this.dialog,
            _t("Remove Group"),
            _t("Remove %s? Its people stay in the list without a group.", group.name)
        );
        if (!sure) {
            return;
        }
        const leaders = await this.orm.call("hr.employee", "crew_shift_group_leaders", []);
        if (!leaders.length) {
            this.notification.add(_t("There is no crew leader to divide the groups."), { type: "danger" });
            return;
        }
        // имената на останалите групи се пазят
        const groups = crewShiftState.groups
            .filter((g) => g.id !== group.id)
            .map((g) => ({ name: g.name, employee_ids: g.employee_ids }));
        return this.saveGroups(groups, leaders[0]);
    },

    saveGroups(groups, leader) {
        // бригадирът дели на групи — с неговия ПИН
        return new Promise((resolve) => {
            const close = this.dialog.add(
                DialogWrapper,
                {
                    Component: PinPopup,
                    componentProps: {
                        popupData: {
                            employee: { id: leader.id, name: leader.name },
                            crewLeader: _t("Crew leader: %s", leader.name),
                        },
                        onClosePopup: () => close(),
                        onPinValidate: async (_employeeId, pin) => {
                            const res = await this.orm.call("hr.employee", "crew_shift_groups_save", [
                                leader.id,
                                pin,
                                groups,
                            ]);
                            if (!res.ok) {
                                this.notification.add(
                                    res.error === "pin" ? _t("Wrong password!") : _t("The groups cannot be saved."),
                                    { type: "danger" }
                                );
                                return false;
                            }
                            this.notification.add(_t("Groups: %s", res.groups), { type: "success" });
                            return true;
                        },
                    },
                },
                { onClose: async () => { await this.reloadAll(); resolve(); } }
            );
        });
    },

    async reloadAll() {
        if (this.props.updateEmployees) {
            await this.props.updateEmployees();
        }
        await this.refreshCrews();
        if (this.env.reload) {
            await this.env.reload();
        }
    },

    async setCrewShiftMode(mode) {
        crewShiftState.mode = await this.orm.call("hr.employee", "crew_shift_set_mode", [mode]);
        await this.reloadAll();
    },

    async selectCrew(crew) {
        await this.orm.call("hr.employee", "crew_shift_select", [crew.id]);
        await this.reloadAll();
    },

    async editCrews() {
        const crews = await this.orm.call("hr.employee", "crew_shift_crews", []);
        this.dialog.add(CrewShiftDialog, {
            crews,
            onConfirm: (ids) => this.applyCrews(crews, ids),
        });
    },

    async applyCrews(crews, ids) {
        const removed = crews.filter((c) => c.on_shift && !ids.includes(c.id));
        const added = crews.filter((c) => !c.on_shift && ids.includes(c.id));
        if (removed.length) {
            const leave = await confirmDialog(
                this.dialog,
                _t("Leave All Work Orders?"),
                _t("%s will leave all work orders. Continue?", removed.map((c) => c.name).join(", "))
            );
            if (leave) {
                // „Да“ — бригадите излизат и хората им спират работа навсякъде;
                // „Не“ — остават си в списъка
                await this.orm.call("hr.employee", "crew_shift_remove", [removed.map((c) => c.id), true]);
            }
        }
        for (const crew of added) {
            await this.askLeaderPin(crew);
        }
        await this.reloadAll();
    },

    askLeaderPin(crew) {
        return new Promise((resolve) => {
            const close = this.dialog.add(
                DialogWrapper,
                {
                    Component: PinPopup,
                    componentProps: {
                        popupData: {
                            employee: { id: crew.leader_id, name: crew.leader_name },
                            crewLeader: _t("Crew leader of %(crew)s: %(name)s", {
                                crew: crew.name,
                                name: crew.leader_name,
                            }),
                        },
                        onClosePopup: () => close(),
                        onPinValidate: async (_employeeId, pin) => {
                            const res = await this.orm.call("hr.employee", "crew_shift_add", [crew.id, pin]);
                            if (!res.ok) {
                                this.notification.add(
                                    res.error === "pin" ? _t("Wrong password!") : _t("The crew cannot be added."),
                                    { type: "danger" }
                                );
                                return false;
                            }
                            this.notification.add(_t("Crew on shift: %s", crew.name), { type: "success" });
                            return true;
                        },
                    },
                },
                { onClose: () => resolve() }
            );
        });
    },

    kick() {
        const selected = crewShiftState.crews.find((c) => c.id === crewShiftState.selected);
        const group = crewShiftState.groups.find((g) => g.id === crewShiftState.groupSelected);
        const selectedName =
            crewShiftState.mode === "crew"
                ? selected?.name
                : crewShiftState.mode === "group"
                ? group?.name
                : this.props.employees.admin?.name;
        this.dialog.add(CrewShiftKickDialog, {
            selectedName: selectedName || "",
            onKick: async (scope) => {
                if (scope === "all") {
                    const sure = await confirmDialog(
                        this.dialog,
                        _t("Kick Out of the Work Orders"),
                        _t("Kick everyone out of the work orders?")
                    );
                    if (!sure) {
                        return;
                    }
                }
                const count = await this.orm.call("hr.employee", "crew_shift_kick", [scope]);
                this.notification.add(_t("Stopped working: %s", count), { type: "success" });
                await this.reloadAll();
            },
        });
    },
});
