# simulated-market

Give an app a task, let software visitors try it, and inspect the steps behind the result. NVIDIA Nemotron on Nebius Token Factory drives the optional full run. The visitors are models, not people. They read pages; they do not sign in, type, buy, upload or save in the app being tested.

`workspace/recorded-evidence.json` and the recorded replay contain selected historical excerpts and hashes; their `source` paths name the author's local evidence, which is not bundled or available as runnable paths in this snapshot.

This source snapshot starts with an empty private store. It includes the application, browser interface, model adapters, schemas and small public demo fixtures. It contains no full study archives or provider credentials; the legacy replay includes the bounded historical excerpts described above. A basic browser check works without a model key. Full inference and deeper model reports require your own Nebius Token Factory key and separate authorization to incur provider charges.

## Start with a basic check

Use macOS or Linux with Python 3.10 or newer. The verified cold install used Python 3.12 on macOS. Windows is not supported by the workspace's file locking. The first dependency and browser installation needs internet access.

```sh
python3 -m venv .venv-app
.venv-app/bin/python -m pip install -r requirements-app-check.txt
.venv-app/bin/python -m playwright install chromium
.venv-app/bin/python -m sim workspace --store ../private-app-check-store --port 3878
```

Choose a new private store outside the checkout. Open the private link printed by the command. Select **Basic check · does it load**, paste the address of a running app and start. Inspect the checks and saved screens, then reload and reopen the same saved result. A code-only repository link returns an explanation; source from that repository is not installed or run.

This startup command keeps model visitors, model reports and sponsor execution off. A basic check can establish that a page opens and a reading link works; it cannot establish complete task success or human usability. The saved store is private and must not be committed or put on a public server.

## Model visitors

See [the app-check guide](docs/app-check.md) for the full-run interface, its limits and explicit enablement. The configured model is NVIDIA Nemotron Nano through Nebius Token Factory. Full model use makes billable inference requests. It is distinct from the basic check and from replaying saved screens. No judge-hosted deployment, human validation, revenue forecast or prediction accuracy is established by this source snapshot.

## First Users direction

The ambition is to pair simulated visitors with verified human first visits: run a bounded task with software visitors, then ask paid, verified humans through FAVOUR to attempt the same task. Keep both reports separate and measure where they agree. That human flow, its supply, payments and calibration are planned; no integration or human result is claimed here. The first offer to test is EUR19 for one check, before subscription plans. There are no sales or live payments.

## Supporting paths

`sim/task_contract.py` and `sim/task_rail.py` preserve ordered read-only task requirements. Explicitly requested `sim/docs_rescue.py` searches official documentation with Tavily; it requires paid-call authorization and does not establish task completion. `sim/payment_stub.py` is a labelled local billing prototype, not a checkout or live entitlement service. See [task contracts](docs/task-contract.md) and [payment and scale design](docs/payment-scale.md). The `/tools` workspace is the app-check interface.

## Source scope

[SOURCE-ALLOWLIST.txt](SOURCE-ALLOWLIST.txt) names every included file. Private research archives, invitation and registration records, working instructions, historical logs, account data and saved model traces are omitted. The original private repository remains intact. The public history starts with a fresh source snapshot; later reviewed changes contain no private ancestor history.

The earlier document/CLI comparison code and its public python-dotenv fixture remain available as supporting modules. Their original working reports, studies and internal build guide are not included. The main supported startup path here is the app-check workspace above.

## Checks

The two focused app test modules are included. To run them, install pytest in your development environment and run `python -m pytest tests/test_app_check.py tests/test_app_swarm.py`. They use local fixtures and replace provider effects; they do not establish new live inference or real human use.

## License and third-party material

The project source is under [MIT](LICENSE). The public python-dotenv demo target retains its BSD license at [target/python-dotenv/LICENSE.python-dotenv](target/python-dotenv/LICENSE.python-dotenv). Keep third-party notices when distributing the source. Dependency installation fetches packages governed by their own licenses.
