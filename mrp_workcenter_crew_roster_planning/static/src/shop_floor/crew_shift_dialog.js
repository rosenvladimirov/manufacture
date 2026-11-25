import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState } from "@odoo/owl";

/** „Редактиране на бригади“: отбелязват се бригадите на смяната. */
export class CrewShiftDialog extends Component {
    static template = "mrp_workcenter_crew_roster_planning.CrewShiftDialog";
    static components = { Dialog };
    static props = {
        crews: Array,
        onConfirm: Function,
        close: Function,
    };

    setup() {
        this.selected = useState({ ids: this.props.crews.filter((c) => c.on_shift).map((c) => c.id) });
    }

    toggle(crew) {
        const index = this.selected.ids.indexOf(crew.id);
        if (index >= 0) {
            this.selected.ids.splice(index, 1);
        } else {
            this.selected.ids.push(crew.id);
        }
    }

    confirm() {
        const ids = [...this.selected.ids];
        this.props.close();
        this.props.onConfirm(ids);
    }
}

/** „Изритай“: избраните или всички. */
export class CrewShiftKickDialog extends Component {
    static template = "mrp_workcenter_crew_roster_planning.CrewShiftKickDialog";
    static components = { Dialog };
    static props = {
        selectedName: { type: String, optional: true },
        onKick: Function,
        close: Function,
    };

    kick(scope) {
        this.props.close();
        this.props.onKick(scope);
    }
}

/** „Редактиране на групи“: всеки човек от списъка — в една група (Росен 16.10.2026). */
export class CrewShiftGroupDialog extends Component {
    static template = "mrp_workcenter_crew_roster_planning.CrewShiftGroupDialog";
    static components = { Dialog };
    static props = {
        people: Array,
        groups: Array,
        leaders: Array,
        onConfirm: Function,
        close: Function,
    };

    setup() {
        const assign = {};
        this.props.groups.forEach((group, index) => {
            for (const id of group.employee_ids) {
                assign[id] = index + 1;
            }
        });
        this.state = useState({
            assign,
            count: Math.max(2, this.props.groups.length),
            leaderId: this.props.leaders.length ? this.props.leaders[0].id : false,
        });
    }

    get numbers() {
        return Array.from({ length: this.state.count }, (_v, i) => i + 1);
    }

    setGroup(person, number) {
        this.state.assign[person.id] = this.state.assign[person.id] === number ? 0 : number;
    }

    addGroup() {
        this.state.count += 1;
    }

    removeGroup(number) {
        // хората на групата остават без група, по-горните групи слизат с едно
        for (const [id, n] of Object.entries(this.state.assign)) {
            if (n === number) {
                this.state.assign[id] = 0;
            } else if (n > number) {
                this.state.assign[id] = n - 1;
            }
        }
        this.state.count = Math.max(1, this.state.count - 1);
    }

    clearGroups() {
        for (const id of Object.keys(this.state.assign)) {
            this.state.assign[id] = 0;
        }
        this.state.count = 1;
    }

    confirm() {
        const groups = this.numbers.map((n) =>
            this.props.people.filter((p) => this.state.assign[p.id] === n).map((p) => p.id)
        );
        const leader = this.props.leaders.find((l) => l.id === Number(this.state.leaderId));
        this.props.close();
        this.props.onConfirm(groups, leader);
    }
}
