/** Режимът на панела с хората в Shop Floor и бригадите на смяната — споделени между
 *  панела и картите на поръчките (Росен 15.10.2026). Пазят се в сесията на сървъра. */
import { reactive } from "@odoo/owl";

export const crewShiftState = reactive({
    mode: "people",
    leaders: {},
    crews: [],
    selected: false,
    groups: [],
    groupSelected: false,
    refresh: null,
});
