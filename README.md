# Preflight

Find what breaks when an Odoo module moves to a newer version, before you install it there.

**Try it in the browser: [odoo-upgrade-check-five.vercel.app](https://odoo-upgrade-check-five.vercel.app)**. Paste a model, a view or a JS file and see the result.

```text
$ odoo-preflight pos_vietqr
pos_vietqr/__manifest__.py:16:10  error  Odoo 17 has no asset bundle 'point_of_sale.assets'. [removed-dependency]
    → "point_of_sale._assets_pos"
pos_vietqr/static/src/js/payment_vietqr.js:6:25  error  Odoo 17 has no legacy module 'point_of_sale.models': rewrite this file as an ES module. [removed-js-module]
pos_vietqr/views/pos_payment_method_views.xml:9:17  error  Since Odoo 17 views reject attrs: the module cannot be installed. [view-attrs]
    → invisible="use_payment_terminal != 'vietqr'" required="use_payment_terminal == 'vietqr'"
...

1 module(s) checked: 14 error(s), 1 warning(s).
```

It reads Python, XML views and data, JavaScript and manifests, and reports each problem
with its file and line, why it breaks, and the replacement when there is one. `attrs` and
`states` are converted to the Odoo 17 expressions for you to paste.

It changes nothing in your code, needs no database and no Odoo installation, and has no
dependencies.

## Install

```sh
pipx install git+https://github.com/thanhphu2643/odoo-preflight
```

Python 3.9 or newer.

## Use

```sh
odoo-preflight path/to/addons            # each module to the next version (16 -> 17)
odoo-preflight my_module --to 18         # 16 -> 18: the 17 and 18 rules together
odoo-preflight . --from 16 --to 17       # when the manifest version does not say
odoo-preflight . --format json           # for scripts
odoo-preflight --list-rules
```

It exits with 1 when it finds an error (`--strict`: a warning too), so it can gate CI.

**GitHub Actions**: with `--format github`, the findings show up on the lines of the pull request.

```yaml
- run: pipx install git+https://github.com/thanhphu2643/odoo-preflight
- run: odoo-preflight . --to 17 --format github
```

**pre-commit**

```yaml
- repo: https://github.com/thanhphu2643/odoo-preflight
  rev: main
  hooks:
    - id: odoo-preflight
      args: [--to, "17"]
```

## What it finds

Errors break the module in that version: it cannot be installed, it crashes, or, worse,
it runs but silently stops doing what it did. Warnings are deprecations that still work.

| Rule | Odoo | | |
|---|---|---|---|
| `view-attrs` | 17 | error | `attrs` and `states` in views, with the expressions to use instead |
| `name-get` | 17 | error | Overriding `name_get()` is ignored: the display name comes from `_compute_display_name()` |
| `name-search-signature` | 17 | error | `_name_search(name, args, ..., name_get_uid)` became `_name_search(name, domain, ..., order)` |
| `field-states` | 17 | error | `fields.X(states=...)` is ignored |
| `read-group-signature` | 17 | error | `_read_group()` takes `(domain, groupby, aggregates)` and returns tuples |
| `env-translate` | 17 | error | `env._t` is gone: import `_t` |
| `field-registry` | 17 | error | The fields registry holds `{ component }` objects |
| `name-get-call` | 17 | warning | `name_get()` calls |
| `list-view` | 18 | error | `<tree>`, `//tree` xpaths and `view_mode="tree"` |
| `name-search-removed` | 18 | error | `_name_search()` is ignored: override `_search_display_name()` |
| `name-get-removed` | 18 | error | `name_get()` no longer exists |
| `user-has-groups` | 18 | error | `user_has_groups()` no longer exists |
| `rpc-service` | 18 | error | `useService("rpc")`: import `rpc` instead |
| `group-operator` | 18 | warning | `group_operator=` became `aggregator=` |
| `access-methods` | 18 | warning | `check_access_rights()`, `check_access_rule()`, `_filter_access_rules()` |
| `kanban-box` | 18 | warning | The `kanban-box` template became `card` |
| `manifest-version` | any | warning | The manifest version is not for the target version |

And, from the comparison of each version with the previous one, anything the newer
version no longer has:

| Rule | 16 → 17 | 17 → 18 |
|---|---|---|
| `removed-dependency`: modules in `depends`, asset bundles | 33 modules, 21 bundles | 32 modules, 4 bundles |
| `removed-model`: models in Python and XML | 43 | 29 |
| `removed-field`: fields in views, xpaths, data records, `self.x`, `@api.depends`, domains and values of `env['model']` calls | 175 | 103 |
| `removed-reference`: views in `inherit_id`, `ref`, `t-call`; templates in `t-inherit` | 369 views, 601 templates | 319 views, 181 templates |
| `removed-js-module`: ES imports and legacy `require()` | 1,008 + 619 legacy | 302 + 1 legacy |

For example `stock.move.line.qty_done` (17), the `mail.channel` model (17, now
`discuss.channel`), `ir.cron.numbercall` (18) or `product.template.detailed_type` (18).

## How it was checked

- **Every rule against the Odoo source code** of the version it names. For example, the
  17 view validator rejects `attrs`, the 17 `name_get()` is no longer used by
  `display_name`, and Odoo 18 has no `rpc` service.
- **The removed lists are extracted from the source code** of the official `odoo:16`,
  `odoo:17` and `odoo:18` images (Community) by `tools/build_data.py`. Nothing in them is
  written by hand.
- **On a real module, both ways.** [l10n_vn_address](https://github.com/thanhphu2643/odoo-vn-address)
  (Odoo 16) was moved to 17, then to 18, changing only what the tool reported:
  - It installed and its 18 tests passed on both.
  - Before the 18 fixes, the module failed to install on `<tree>`, as reported.
  - Two of its tests failed because `_name_search()` was silently ignored, also as
    reported, although Odoo itself printed no error.

## Limits

- It is static analysis. Code that builds model or field names at run time, or a record
  whose model is not written in the code, is not followed.
- The removed lists cover Odoo Community. A field that moved to Enterprise is reported as
  removed.
- JavaScript is read line by line, not parsed.
- It covers 16 → 17 and 17 → 18.

[OCA/odoo-module-migrator](https://github.com/OCA/odoo-module-migrator) takes another
approach: it rewrites the code and commits the changes. This tool only reports, so it can
run in CI on every pull request.

## Development

```sh
python -m unittest discover -s tests -t .
python tools/build_data.py   # regenerate src/odoo_preflight/data/ (needs Docker)
python -m web.app            # the demo page on http://localhost:8000
```

## License

MIT
