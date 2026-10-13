'use strict';

const studySection = document.querySelector('#study');
const studyBody = document.querySelector('#study-body');
const studyError = document.querySelector('#study-error');
const studyToken = sessionStorage.getItem('workspace-token') || '';
const variantNames = {base: 'Original', guidance: 'Task guidance', formatting: 'Formatting rewrite'};
const phases = [['contract', '1 · Change'], ['forecast', '2 · Simulation'],
                ['observed', '3 · Recorded runs'], ['decision', '4 · Decision'], ['people', '5 · People']];
let studyData = null, studyDecisions = [], studyFamily = 'pydantic', studyPhase = 'contract';
let studyBudget = 12, studyRevealed = false, studyCandidate = 'guidance';

function studyNode(tag, value, parent, className) {
  const node = document.createElement(tag);
  if (value !== null) node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

async function studyApi(path, body) {
  const response = await fetch('/api/' + path, {
    method: body ? 'POST' : 'GET',
    headers: {'X-Workspace-Token': studyToken, ...(body ? {'Content-Type': 'application/json'} : {})},
    ...(body ? {body: JSON.stringify(body)} : {}),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'The study could not be opened.');
  return data;
}

const count = (family, variant) => studyData.episodes.filter(row => row.family === family && row.variant === variant);
const percent = value => `${(value * 100).toFixed(0)}%`;
const cash = value => `$${value.toFixed(3)}`;

function studyShell() {
  studyBody.replaceChildren();
  const head = studyNode('div', null, studyBody, 'study-head');
  const intro = studyNode('div', null, head);
  studyNode('p', '48 registered attempts · 4 untouched source families · 3 versions · 4 seeds', intro, 'label');
  studyNode('p', 'Frozen forecast first. Recorded behaviour second. Your decision stays yours.', intro);
  const label = studyNode('label', 'Choose a software project', head);
  const select = studyNode('select', null, label);
  for (const family of Object.keys(studyData.families).sort()) {
    const option = studyNode('option', family, select);
    option.value = family;
  }
  select.value = studyFamily;
  select.onchange = () => { studyFamily = select.value; studyPhase = 'contract'; studyRevealed = false; studyShell(); };
  const nav = studyNode('div', null, studyBody, 'study-tabs');
  for (const [phase, labelText] of phases) {
    const button = studyNode('button', labelText, nav);
    button.type = 'button';
    if (phase === studyPhase) button.setAttribute('aria-current', 'step');
    button.onclick = () => { studyPhase = phase; studyShell(); };
  }
  const stage = studyNode('div', null, studyBody, 'study-stage');
  ({contract: renderContract, forecast: renderForecast, observed: renderObserved,
    decision: renderDecision, people: renderPeople})[studyPhase](stage);
}

function renderContract(stage) {
  const family = studyData.families[studyFamily];
  studyNode('h3', `${studyFamily} ${family.package_version}`, stage);
  studyNode('p', studyData.tasks[studyFamily], stage);
  studyNode('p', `Source: ${family.canonical_source}. The task, package version, evaluator, container, model, seeds and call limit were registered before these outcomes.`, stage, 'small');
  const cards = studyNode('div', null, stage, 'study-cards');
  for (const variant of ['base', 'guidance', 'formatting']) {
    const card = studyNode('article', null, cards);
    studyNode('h3', variantNames[variant], card);
    studyNode('p', variant === 'base' ? 'Published documentation' : 'A registered alternative to the original', card);
    studyNode('p', 'Document ' + family.variant_hashes[variant].slice(0, 12), card, 'small');
  }
  const controls = studyNode('div', null, stage, 'study-actions');
  const candidateLabel = studyNode('label', 'Compare original with', controls);
  const candidate = studyNode('select', null, candidateLabel);
  for (const value of ['guidance', 'formatting']) {
    const option = studyNode('option', variantNames[value], candidate);
    option.value = value;
  }
  candidate.value = studyCandidate;
  candidate.onchange = () => { studyCandidate = candidate.value; renderDocs(); };
  const docs = studyNode('div', null, stage, 'study-docs');
  function renderDocs() {
    docs.replaceChildren();
    for (const variant of ['base', studyCandidate]) {
      const card = studyNode('div', null, docs);
      studyNode('h3', variantNames[variant], card);
      const original = studyData.documents[studyFamily].base.text;
      const documentText = studyData.documents[studyFamily][variant].text;
      let firstDifference = 0;
      while (firstDifference < Math.min(original.length, documentText.length) &&
             original[firstDifference] === documentText[firstDifference]) firstDifference++;
      const start = Math.max(0, firstDifference - 100);
      const excerpt = documentText.slice(start, firstDifference + 600);
      studyNode('p', `Document excerpt near the first change (${documentText.length.toLocaleString()} characters total)`, card, 'small');
      studyNode('pre', (start ? '…\n' : '') + excerpt + (firstDifference + 600 < documentText.length ? '\n…' : ''), card);
      const full = studyNode('details', null, card);
      studyNode('summary', 'Open full registered document', full);
      studyNode('pre', documentText, full);
    }
  }
  renderDocs();
  const next = studyNode('button', 'Explore the locked simulation →', stage, 'primary');
  next.onclick = () => { studyPhase = 'forecast'; studyShell(); };
}

function renderForecast(stage) {
  studyNode('h3', 'What the model predicted before these runs', stage);
  studyNode('p', `Fitted on ${studyData.training.episodes} earlier agent episodes across ${studyData.training.families.length} other source families. These predictions were locked before the 48 heldout agents ran.`, stage);
  studyNode('p', 'The model predicts from intervention category, task state and call budget. It does not read the patch or distinguish these four projects. All three forecasts abstain. Do not turn a probability here into a ship recommendation.', stage, 'study-warning');
  const label = studyNode('label', `Model-call budget: ${studyBudget} of ${studyData.population.step_limit}`, stage);
  const slider = studyNode('input', null, label);
  slider.type = 'range'; slider.min = '1'; slider.max = String(studyData.population.step_limit);
  slider.value = String(studyBudget);
  const cards = studyNode('div', null, stage, 'study-cards');
  function draw() {
    label.firstChild.textContent = `Model-call budget: ${studyBudget} of ${studyData.population.step_limit}`;
    cards.replaceChildren();
    for (const variant of ['base', 'guidance', 'formatting']) {
      const prediction = studyData.forecast[variant];
      const curve = prediction.curve[studyBudget - 1];
      const card = studyNode('article', null, cards);
      studyNode('h3', variantNames[variant], card);
      studyNode('p', percent(curve.goal), card, 'study-number');
      studyNode('p', 'Model mass on goal or completed state at this call budget', card, 'small');
      const bar = studyNode('div', null, card, 'study-bar');
      const fill = studyNode('span', null, bar);
      fill.style.width = percent(curve.goal);
      studyNode('p', `${percent(curve.unknown)} unsupported path mass · ABSTAIN`, card, 'small');
      const detail = studyNode('details', null, card);
      studyNode('summary', 'Predicted state distribution', detail);
      for (const [state, mass] of Object.entries(curve.states))
        studyNode('p', `${state.replaceAll('_', ' ')}: ${percent(mass)}`, detail, 'small');
    }
  }
  slider.oninput = () => { studyBudget = Number(slider.value); draw(); };
  draw();
  const next = studyNode('button', 'Reveal the recorded agents →', stage, 'primary');
  next.onclick = () => { studyPhase = 'observed'; studyShell(); };
}

function renderObserved(stage) {
  studyNode('h3', 'What the hosted agents actually did', stage);
  if (!studyRevealed) {
    studyNode('p', 'These are finished NVIDIA model calls, replayed from a registered study. Revealing them makes no provider request.', stage);
    const reveal = studyNode('button', 'Reveal all recorded outcomes', stage, 'primary');
    reveal.onclick = () => { studyRevealed = true; studyShell(); };
    return;
  }
  const cards = studyNode('div', null, stage, 'study-cards');
  for (const variant of ['base', 'guidance', 'formatting']) {
    const rows = count(studyFamily, variant);
    const correct = rows.filter(row => row.final_pass === true).length;
    const card = studyNode('article', null, cards);
    studyNode('h3', variantNames[variant], card);
    studyNode('p', `${correct} / ${rows.length}`, card, 'study-number');
    studyNode('p', 'final artifacts passed the registered checks', card, 'small');
    const locked = studyData.forecast[variant];
    const scoredPoint = locked.supported_goal_probability + .5 * locked.unsupported_mass;
    studyNode('p', `${percent(scoredPoint)} locked scoring probability · ${percent(correct / rows.length)} observed rate`, card, 'small');
    studyNode('p', `${rows.reduce((total, row) => total + row.provider_calls, 0)} model calls · ${cash(rows.reduce((total, row) => total + row.controller_usd, 0))} controller cost`, card, 'small');
  }
  studyNode('p', 'Final correctness includes every attempted run, including API errors and limit exits. Submission alone is not success. These version differences do not establish a causal docs effect.', stage, 'study-warning');
  studyNode('h3', 'Open an agent journey', stage);
  for (const variant of ['base', 'guidance', 'formatting']) {
    for (const row of count(studyFamily, variant)) {
      const detail = studyNode('details', null, stage, 'study-trial');
      const state = row.final_pass === true ? 'passed' : 'did not pass';
      studyNode('summary', `${variantNames[variant]} · seed ${row.seed} · ${state} · ${row.exit}${row.error_type ? ' (' + row.error_type + ')' : ''}`, detail);
      if (row.final_pass === true && row.exit === 'harness_error')
        studyNode('p', 'The final artifact passed its checks, but the agent then ended with an API error. Both facts are retained.', detail, 'study-warning');
      studyNode('p', `Observed path: ${row.states.join(' → ')}. ${row.provider_calls} model calls, ${cash(row.controller_usd)}.`, detail, 'small');
      row.steps.forEach((step, index) => {
        studyNode('p', `Step ${index + 1}: ${step.state} · return ${step.returncode ?? 'unknown'}`, detail, 'small');
        studyNode('pre', step.command || '(no command recorded)', detail);
      });
      const checks = studyNode('details', null, detail);
      studyNode('summary', 'Controller final checks', checks);
      studyNode('pre', JSON.stringify(row.checks, null, 2), checks);
    }
  }
  const scores = studyNode('article', null, stage);
  studyNode('h3', 'Did the forecast help on unseen projects?', scores);
  const aggregate = ['base', 'guidance', 'formatting'].map(variant => {
    const rows = studyData.episodes.filter(row => row.variant === variant);
    return `${variantNames[variant]} ${rows.filter(row => row.final_pass === true).length}/${rows.length}`;
  });
  studyNode('p', `${aggregate.join(' · ')} final artifacts passed. Neither alternative beats the original in aggregate.`, scores);
  studyNode('p', `${studyData.scores.brier.toFixed(3)} forecast Brier loss · ${studyData.scores.no_change_brier.toFixed(3)} retrospective same-family no-change · ${studyData.scores.pooled_brier.toFixed(3)} pooled training. Lower is better.`, scores);
  studyNode('p', 'Scored on 32 candidate outcomes with equal family and candidate weight. The edge is small, and all four families got the same forecast for a given candidate. This is a diagnostic result, not established calibration.', scores, 'small');
  const total = studyData.episodes;
  const exits = new Map();
  total.forEach(row => exits.set(row.exit, (exits.get(row.exit) || 0) + 1));
  studyNode('p', `Across all ${total.length} runs: ${[...exits].map(([key, value]) => `${value} ${key}`).join(' · ')}. ${studyData.controller.requests_forwarded} model requests, ${cash(studyData.controller.committed_usd)} controller-calculated model cost.`, scores, 'small');
  studyNode('p', studyData.limits.cost_scope, scores, 'small');
  const next = studyNode('button', 'Record your decision →', stage, 'primary');
  next.onclick = () => { studyPhase = 'decision'; studyShell(); };
}

function renderDecision(stage) {
  studyNode('h3', `Decision for ${studyFamily}`, stage);
  studyNode('p', 'The model abstained. Choose what to keep or test next, based on the recorded paths. This local decision does not publish or change documentation.', stage, 'study-warning');
  const form = studyNode('form', null, stage);
  const label = studyNode('label', 'Decision', form);
  const choice = studyNode('select', null, label);
  for (const [value, text] of [['defer', 'Defer: more evidence needed'], ['base', 'Keep original'],
                              ['guidance', 'Choose task guidance'], ['formatting', 'Choose formatting rewrite']]) {
    const option = studyNode('option', text, choice); option.value = value;
  }
  const reasonLabel = studyNode('label', 'What in the record led to this decision?', form);
  const reason = studyNode('textarea', null, reasonLabel); reason.rows = 3; reason.required = true;
  const save = studyNode('button', 'Save decision privately', form, 'primary'); save.type = 'submit';
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true; studyError.textContent = '';
    try {
      const response = await studyApi('study/decision', {
        manifest: studyData.identities.manifest, forecast: studyData.identities.forecast,
        family: studyFamily, choice: choice.value, reason: reason.value,
      });
      studyDecisions = response.decisions; studyShell();
    } catch (error) { studyError.textContent = error.message; save.disabled = false; }
  };
  const history = studyDecisions.filter(row => row.family === studyFamily);
  studyNode('h3', `Saved decisions (${history.length})`, stage);
  if (!history.length) studyNode('p', 'No decision recorded yet.', stage, 'small');
  for (const row of [...history].reverse()) {
    const item = studyNode('div', null, stage, 'study-history');
    studyNode('p', `${new Date(row.at).toLocaleString()} · ${row.choice}`, item);
    studyNode('p', row.reason, item, 'small');
  }
}

function renderPeople(stage) {
  studyNode('h3', 'Return with people', stage);
  studyNode('p', 'No human observations are attached to this study. Agent runs can calibrate an agent simulation; they cannot validate a prediction about people.', stage, 'study-warning');
  studyNode('p', 'The private workspace can freeze a separate consented human trial after a completed own-project comparison. It records the person’s task result against the same starting environment and time limit. That evidence remains a separate population.', stage);
  studyNode('p', 'Next impact measure: can a builder choose a documentation change before release, then score that choice against unaided user outcomes? This has not been measured.', stage, 'small');
}

studyApi('study').then(response => {
  studyData = response.study; studyDecisions = response.decisions;
  if (!studyData.families[studyFamily]) studyFamily = Object.keys(studyData.families).sort()[0];
  studySection.hidden = false; document.querySelector('#study-link').hidden = false;
  document.querySelector('#backend-label').textContent = 'RECORDED AGENT STUDY · HOSTED RUNS';
  const intro = document.querySelector('main > h1');
  intro.textContent = 'What happened when we changed the docs?';
  intro.nextElementSibling.textContent = 'One frozen prediction. Forty-eight agent attempts. Inspect the paths before deciding what to ship.';
  intro.nextElementSibling.nextElementSibling.hidden = true;
  studyShell();
}).catch(error => {
  if (error.message !== 'No recorded study was selected at startup.') studyError.textContent = error.message;
});
