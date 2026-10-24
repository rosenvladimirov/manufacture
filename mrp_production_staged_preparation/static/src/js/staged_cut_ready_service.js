/** @odoo-module **/
// Любо 21.10 (TG 173291): „не може ли директно да ми се отвори формата за
// одобрение?“ — когато разкроят е готов: ако човекът е в Производство,
// формата за одобрение се отваря сама; иначе — известие с бутон „Одобри“,
// което стои, докато не го затвори.
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

export const stagedCutReadyService = {
    dependencies: ["bus_service", "notification", "action", "orm"],
    start(env, { bus_service, notification, action, orm }) {
        const openApproval = async (productionIds) => {
            const act = await orm.call(
                "mrp.production", "action_staged_review_cutting", [productionIds]
            );
            await action.doAction(act);
        };
        bus_service.subscribe("staged_cut_ready", async (payload) => {
            const ids = payload.production_ids || [];
            const controller = action.currentController;
            const model = controller && controller.props && controller.props.resModel;
            if (model === "mrp.production") {
                await openApproval(ids);
                return;
            }
            const close = notification.add(payload.names || "", {
                title: _t("Cutting ready — approve it"),
                type: "warning",
                sticky: true,
                buttons: [
                    {
                        name: _t("Approve"),
                        primary: true,
                        onClick: async () => {
                            close();
                            await openApproval(ids);
                        },
                    },
                ],
            });
        });
    },
};

registry.category("services").add("staged_cut_ready", stagedCutReadyService);
