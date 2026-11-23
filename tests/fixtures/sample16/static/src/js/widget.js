/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CharField } from "@web/views/fields/char/char_field";
import { PosGlobalState } from "@point_of_sale/js/models";

export class WeightField extends CharField {
    setup() {
        super.setup();
        this.rpc = useService("rpc");
        this.title = this.env._t("Weight");
    }
}

registry.category("fields").add("weight", WeightField);
