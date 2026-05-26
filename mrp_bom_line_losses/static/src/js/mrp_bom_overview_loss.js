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
    // Allow negative values (efficiency gain) down to -99%
    // Factor = 1 + ratio must stay > 0, so ratio > -1 → percent > -100
    if (value <= -100) {
        return -99;
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
        this.lossQtyState = useState({ value: null });
        this.lossCostState = useState({ value: null });
        this.lossPercentState = useState({ value: null });
        this.lossEditingState = useState({ value: false });
        this.lossInputRef = useRef("lossInput");
    },

    get lossQtyDisplay() {
        if (this.lossQtyState.value !== null && this.lossQtyState.value !== undefined) {
            return this.lossQtyState.value;
        }
        if (Object.prototype.hasOwnProperty.call(this.data, "qty_with_loss")) {
            return this.data.qty_with_loss;
        }
        return this.data.quantity;
    },

    get lossPercentDisplay() {
        if (this.lossPercentState.value !== null && this.lossPercentState.value !== undefined) {
            return this.lossPercentState.value;
        }
        return (this.data.loss || 0) * 100;
    },

    get lossCostDisplay() {
        if (this.lossCostState.value !== null && this.lossCostState.value !== undefined) {
            return this.lossCostState.value;
        }
        if (Object.prototype.hasOwnProperty.call(this.data, "loss_cost")) {
            return this.data.loss_cost;
        }
        return 0;
    },

    onLossInput(ev) {
        const input = ev.target;
        if (!input || input.tagName !== "INPUT") {
            return;
        }
        const baseQty = parseNumber(input.dataset.baseQty);
        if (!Number.isFinite(baseQty)) {
            return;
        }
        const lossPercent = clampPercent(parseNumber(input.value));
        input.value = String(lossPercent);
        const lossRatio = lossPercent / 100;
        this.lossQtyState.value = baseQty * (1 + lossRatio);
        this.lossPercentState.value = lossPercent;
        if (this.data.quantity) {
            const unitCost = this.data.prod_cost / this.data.quantity;
            this.lossCostState.value = unitCost * baseQty * lossRatio;
        } else {
            this.lossCostState.value = 0;
        }
    },

    onLossEditClick(ev) {
        ev.stopPropagation();
        this.lossEditingState.value = true;
        setTimeout(() => {
            const input = this.lossInputRef.el;
            if (input) {
                input.focus();
                input.select();
            }
        }, 0);
    },

    async onLossBlur() {
        const input = this.lossInputRef.el;
        const baseQty = input ? parseNumber(input.dataset.baseQty) : NaN;
        const lossPercent = clampPercent(this.lossPercentState.value);
        if (input) {
            input.value = String(lossPercent);
        }
        this.lossPercentState.value = lossPercent;
        if (Number.isFinite(baseQty)) {
            const lossRatio = lossPercent / 100;
            this.lossQtyState.value = baseQty * (1 + lossRatio);
            if (this.data.quantity) {
                const unitCost = this.data.prod_cost / this.data.quantity;
                this.lossCostState.value = unitCost * baseQty * lossRatio;
            } else {
                this.lossCostState.value = 0;
            }
        }
        this.lossEditingState.value = false;
        if (this.data.line_id) {
            await this.ormService.call("mrp.bom.line", "write", [
                [this.data.line_id],
                { loss: lossPercent / 100 },
            ]);
        }
    },
});
