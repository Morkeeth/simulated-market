# Reading task contracts

The app stores a typed task with intended read/write action and required moves.
The current parser recognizes a bounded set of English and French action words.
A request to read a tutorial about posting stays a reading task; a later request
to upload still requires a write. Return/revisit/revenir/retourner tasks need both
a move away and a recorded return. Unknown action words need clarification before
completion can be reported. This is not general multilingual understanding.

`sim/task_contract.py` contains a strict JSON Schema and builds a proposed Nebius
structured-output request with `response_format.type=json_schema`. It makes no
call. The app currently compiles this shape locally and includes it in the
confirmation prompt and saved job. Exact endpoint schema support and model
interpretation remain unverified. A valid JSON object does not prove its meaning.

`sim/task_rail.py` checks the contract against recorded page transitions apart
from the model confirmation. Invalid contracts fail. Refused/failed page actions
and fragment scrolls do not prove a move or return. A read-only trace cannot
establish a write. Task rules are included in cache identity, so older evidence
is not reused under new completion rules.

This independent function follows the input/output/custom-action pattern of
NeMo Guardrails. It does **not** import, install or execute NVIDIA NeMo Guardrails;
there is no claimed NeMo runtime or safety-model result. It can be wrapped as a
custom action in a future integration. Browser write enforcement remains in the
existing request gate. These checks do not establish all user task steps, target
state persistence, actual model quality or human usability.

Official feature references:
- https://docs.tokenfactory.nebius.com/ai-models-inference/json
- https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/overview

No paid request was made. A future single Nano request with a planning allowance
of 6,000 input and 512 output tokens estimates USD0.00048288 at USD0.06 per million
input and USD0.24 per million output. Token size is an assumption; provider usage
and full cost are unknown. Stop before that runtime check unless separately
allowed. A NeMo deterministic custom action need not make an LLM call.
