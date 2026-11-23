{
    "name": "Sample written for Odoo 16",
    "version": "16.0.1.0.0",
    "depends": ["stock", "note"],
    "data": ["views/views.xml", "data/cron.xml"],
    "assets": {
        "point_of_sale.assets": ["sample16/static/src/js/*"],
        "web.assets_backend": ["sample16/static/src/js/*"],
    },
    "license": "LGPL-3",
}
