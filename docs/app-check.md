# App-check workspace

The path is running-app address, basic browser check or optional model visitors, readable result, then saved screen replay and a deeper report. The browser visits only read. They do not sign in, accept terms, buy, vote, upload, save or publish on the target app.

Start with the README's basic-check command. It generates a fresh private workspace token and keeps optional model calls disabled. Every API request requires `X-Workspace-Token` and same-origin loopback access. Do not publish the token or private store. The server is intended for local use.

## Basic check

`POST /api/app-check/start` accepts `url` and `mode: "quick"`. It creates a private result and starts one browser worker. `GET /api/app-check/results` lists saved results; `GET /api/app-check/result/<id>` opens one; `GET /api/app-check/media/<id>/step-NN.png` returns its saved screen. A repository-only link returns a reason rather than executing its contents. Failed and untested checks remain visible.

## Optional full run

Set `TOKEN_FACTORY_API_KEY` to your own Nebius Token Factory credential in the environment. After obtaining authorization for provider charges, start the workspace with `--allow-app-swarm`. Do not place the credential in a committed file. The registered inference model is `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`.

`POST /api/app-check/job` reads the app and proposes a task. Review or edit it before starting `mode: "swarm"`. Four model visitors attempt that task; one sceptic keeps a separate question. The interface can make one or three tries per visitor. It distinguishes a visitor claiming success, a second check confirming a screen, and recorded steps supporting completion. Tasks that need account access or writes remain untested.

A result is reused only for the same address, task, visitor goals, number of tries, model and step limits. `fresh: true` asks for a new run and can incur new charges. Reopening a saved run does not repeat inference. A local address requires explicit `own_machine: true`; read-only controls remain active. The deeper `/agent-report?visit=<id>` route shows retained call evidence.

Provider requests are reserved against a conservative local cost account before calls, then settled against returned usage. Missing or uncertain usage remains reserved. A full run is bounded by call, per-run cost and account stop limits in `sim/app_swarm.py` and `sim/hosted_cost.py`; those limits do not authorize spending. `--allow-app-report` separately enables a bounded model report after a visit. Leave both flags off for the no-paid basic-check path.

## Limits

Model visitors are not people. Their choices vary, the task checks have limits, and rig-blocked app requests can confound a finding. A screenshot or model claim does not prove demand, human understanding, purchases, adoption or revenue. Results must be inspected at their supporting step. This snapshot includes no retained study corpus and no public judge endpoint.

Phone uses a separate reading view; desktop adds graphs. Replay timing is presentation timing, separate from measured step elapsed time. The planted `/control/` app offers a broken-link control for full model trials; loading its first page in basic mode does not test every planted fault.
