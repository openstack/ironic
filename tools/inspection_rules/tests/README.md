# Inspection Rules Test Cases

Each subdirectory here is an independent test case run by
`ironic-manage inspection-rules check`, and is evaluated against its own
rules, so each test case can exercise different rules. To add a test case,
create a new directory and populate it with three files:

| File | Description |
|------|-------------|
| `node.yaml` or `node.json` | Baremetal node data |
| `inventory.yaml` or `inventory.json` | Hardware inventory and plugin data |
| `rules.yaml` or `rules.json` | Inspection rules to evaluate against the node and inventory |

## Capturing data from a real node

```bash
# Capture node data
openstack baremetal node show <node-id> -f yaml > node.yaml

# Capture hardware inventory
openstack baremetal node inventory save --file inventory.json <node-id>
```

## Running the tests

```bash
tox -e inspection-rules
```

Or invoke the tester directly against a single test case:

```bash
ironic-manage inspection-rules check \
    --rules <test-dir>/rules.yaml \
    --node <test-dir>/node.yaml \
    --inventory <test-dir>/inventory.json
```
