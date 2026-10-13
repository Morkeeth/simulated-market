'use strict';

// The selected file is read in this browser. The workspace never uploads it.
const forecastInput = document.querySelector('#forecast-file');
const forecastBody = document.querySelector('#forecast-body');
const forecastError = document.querySelector('#forecast-error');
const add = (tag, value, parent) => {
  const el = document.createElement(tag);
  el.textContent = value;
  parent.append(el);
  return el;
};
const rate = n => `${(100 * n).toFixed(0)}%`;
const score = n => Number(n).toFixed(3);
const money = n => `$${Number(n).toFixed(3)}`;

function validEvaluation(value) {
  if (value?.kind !== 'heldout-prediction-evaluation' || !Array.isArray(value.families) ||
      !Array.isArray(value.episodes) || value.families.length === 0 || value.episodes.length === 0 ||
      !value.model_sha256 || !value.forecast_lock_sha256 || !value.target_manifest_sha256)
    throw Error('Choose a completed heldout prediction evaluation JSON file.');
  for (const key of ['brier', 'no_change_brier', 'pooled_brier'])
    if (!Number.isFinite(value[key]) || value[key] < 0 || value[key] > 1)
      throw Error('The evaluation has an invalid score.');
  for (const family of value.families) {
    if (typeof family.family !== 'string' || !Array.isArray(family.variants) || family.variants.length !== 2 ||
        !Number.isInteger(family.original_n) || !Number.isInteger(family.original_correct))
      throw Error('The evaluation has an invalid family result.');
    for (const variant of family.variants)
      if (!['guidance', 'formatting'].includes(variant.variant) || !Number.isInteger(variant.n) ||
          !Number.isInteger(variant.final_correct) || !Number.isFinite(variant.prediction) ||
          !Number.isFinite(variant.unsupported_mass) || !Number.isFinite(variant.brier) ||
          !Number.isFinite(variant.no_change_brier) || variant.prediction < 0 || variant.prediction > 1 ||
          variant.unsupported_mass < 0 || variant.unsupported_mass > 1)
        throw Error('The evaluation has an invalid candidate result.');
  }
  for (const row of value.episodes)
    if (typeof row.family !== 'string' || !['base', 'guidance', 'formatting'].includes(row.variant) ||
        !Number.isInteger(row.seed) || !Number.isInteger(row.provider_calls) || row.provider_calls < 0 ||
        !Number.isFinite(row.controller_usd) || row.controller_usd < 0 || typeof row.exit !== 'string')
      throw Error('The evaluation has an invalid episode result.');
  return value;
}

function renderEvaluation(data) {
  forecastBody.replaceChildren();
  add('p', `${data.episodes.length} coding-agent episodes across ${data.families.length} heldout source families. This is a diagnostic simulation result, not evidence about human users.`, forecastBody);
  const summary = add('div', '', forecastBody);
  summary.className = 'grid three';
  for (const [label, value] of [
    ['Locked forecast Brier loss', data.brier],
    ['Same-family no-change baseline', data.no_change_brier],
    ['Pooled training baseline', data.pooled_brier],
  ]) {
    const card = add('article', '', summary);
    add('h3', label, card);
    add('p', score(value), card);
  }
  const delta = data.brier - data.no_change_brier;
  add('p', delta < -0.0005
    ? `The locked forecast has ${score(-delta)} lower Brier loss than the no-change baseline on these families.`
    : delta > 0.0005
      ? `The locked forecast has ${score(delta)} higher Brier loss than the no-change baseline on these families.`
      : 'The locked forecast and no-change baseline have approximately equal Brier loss on these families.', forecastBody);
  add('p', 'Lower Brier loss is better. Each family receives equal weight. The point score assigns probability 0.5 to unsupported mass. Four families cannot establish broad calibration or a reliable prediction advantage.', forecastBody).className = 'small';

  add('h3', 'Predicted and observed outcomes by source family', forecastBody);
  for (const family of data.families) {
    const card = add('article', '', forecastBody);
    add('h3', family.family, card);
    add('p', `Original: ${family.original_correct} of ${family.original_n} reached the final success check.`, card);
    for (const variant of family.variants)
      add('p', `${variant.variant}: predicted ${rate(variant.prediction)} final success; observed ${variant.final_correct} of ${variant.n}; unsupported probability mass ${rate(variant.unsupported_mass)}. Brier ${score(variant.brier)}, no-change ${score(variant.no_change_brier)}.`, card);
  }

  const costs = data.episodes.reduce((sum, row) => sum + row.controller_usd, 0);
  const calls = data.episodes.reduce((sum, row) => sum + row.provider_calls, 0);
  add('h3', 'Effort and cost', forecastBody);
  add('p', `${calls} heldout model requests; ${money(costs)} of controller-calculated heldout model cost.`, forecastBody);
  add('p', 'This excludes training, setup time and the cost of directly testing each candidate. There is no end-to-end cost saving claim.', forecastBody).className = 'small';
  const exits = new Map();
  for (const row of data.episodes) exits.set(row.exit, (exits.get(row.exit) || 0) + 1);
  add('p', 'Run exits: ' + [...exits].map(([name, count]) => `${count} ${name}`).join(' · ') + '. All attempted episodes remain in the score.', forecastBody).className = 'small';
  const identities = add('details', '', forecastBody);
  add('summary', 'Frozen source identities and individual episode results', identities);
  add('p', `Model ${data.model_sha256}; forecast ${data.forecast_lock_sha256}; target registration ${data.target_manifest_sha256}.`, identities).className = 'small';
  add('p', 'This display reads the selected file. It does not verify those hashes; use the campaign evaluator for integrity checks.', identities).className = 'small';
  for (const row of data.episodes)
    add('p', `${row.family} · ${row.variant} · seed ${row.seed}: final ${row.final_pass === true ? 'passed' : 'not passed'}; exit ${row.exit}; first goal at request ${row.first_goal_call ?? 'never'}; ${row.provider_calls} requests; ${money(row.controller_usd)}.`, identities).className = 'small';
}

forecastInput.addEventListener('change', async () => {
  forecastError.textContent = '';
  forecastBody.replaceChildren();
  const file = forecastInput.files?.[0];
  if (!file) return;
  try {
    if (file.size > 2_000_000) throw Error('The selected evaluation file is too large.');
    renderEvaluation(validEvaluation(JSON.parse(await file.text())));
  } catch (error) {
    forecastError.textContent = error instanceof SyntaxError ? 'The file is not valid JSON.' : error.message;
  }
});
