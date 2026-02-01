/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";
import { useRef, useState } from "@odoo/owl";

function parseNumber(value) {
    if (value === undefined || value === null) {
        return NaN;
    }
    const normalized = String(value).replace(",", ".");
    return Number.parseFloat(normalized);
}

function clampPercent(value) {
    if (!Number.isFinite(value)) {
        return 0;
    }
    if (value < 0) {
        return 0;
    }
    if (value > 100) {
        return 100;
    }
    return value;
}

patch(BomOverviewLine.prototype, {
    /**
     * @override
     */
    setup() {
        super.setup();
        this.distQtyState = useState({ value: null });
        this.distPercentState = useState({ value: null });
        this.distEditingState = useState({ value: false });
        this.distInputRef = useRef("distInput");
    },

    get distributionQtyDisplay() {
        if (this.distQtyState.value !== null && this.distQtyState.value !== undefined) {
            return this.distQtyState.value;
        }
        if (Object.prototype.hasOwnProperty.call(this.data, "qty_with_distribution")) {
            return this.data.qty_with_distribution;
        }
        return this.data.quantity;
    },

    get distributionPercentDisplay() {
        if (this.distPercentState.value !== null && this.distPercentState.value !== undefined) {
            return this.distPercentState.value;
        }
        return (this.data.distribution_coefficient || 0) * 100;
    },

    onDistributionInput(ev) {
        const input = ev.target;
        if (!input || input.tagName !== "INPUT") {
            return;
        }
        const baseQty = parseNumber(input.dataset.baseQty);
        if (!Number.isFinite(baseQty)) {
            return;
        }
        const percent = clampPercent(parseNumber(input.value));
        input.value = String(percent);
        const ratio = percent / 100;
        this.distPercentState.value = percent;
        this.distQtyState.value = baseQty * ratio;
    },

    onDistributionEditClick(ev) {
        ev.stopPropagation();
        this.distEditingState.value = true;
        setTimeout(() => {
            const input = this.distInputRef.el;
            if (input) {
                input.focus();
                input.select();
            }
        }, 0);
    },

    async onDistributionBlur() {
        const input = this.distInputRef.el;
        const baseQty = input ? parseNumber(input.dataset.baseQty) : NaN;
        const percent = clampPercent(this.distPercentState.value);
        if (input) {
            input.value = String(percent);
        }
        this.distPercentState.value = percent;
        if (Number.isFinite(baseQty)) {
            const ratio = percent / 100;
            this.distQtyState.value = baseQty * ratio;
        }
        this.distEditingState.value = false;
        if (this.data.line_id) {
            await this.ormService.call("mrp.bom.line", "write", [
                [this.data.line_id],
                { distribution_coefficient: percent / 100 },
            ]);
        }
    },
});
