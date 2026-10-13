// Source-bound summaries of retained local receipts. This file does not run agents.
(() => {
  const cases = [
    {
      id: 'transcripto', tab: '01 · Missing receipt', title: 'A long record disappears',
      fact: 'Both CLI commands exited 0. Only one version passed the separate task check.',
      task: 'Recover the recorded release-check result from a synthetic Codex session.',
      answer: 'proposed', answerText: 'Only the proposed version passed the separate task check.',
      divergenceAt: 1,
      base: { result: '0 / 1 task checks passed', path: [
        'The agent invoked tool replay on the frozen synthetic record. The process exited 0.',
        'The output said the result was unknown and warned that one oversized record was skipped.',
        'The agent submitted. The separate checker rejected the result.'
      ]},
      proposed: { result: '1 / 1 task checks passed', path: [
        'The agent invoked the same tool replay command. The process exited 0.',
        'The output contained the recorded successful result and its source line.',
        'The agent submitted. The separate checker accepted the result.'
      ]},
      divergence: 'The first meaningful divergence is in the CLI output after the same command: the original skips the oversized record; the proposed version includes its result. Exit 0 in both arms did not prove task completion.',
      check: 'Separate networkless controller check: original failed, proposed passed. One local model-driven attempt per version on an assisted synthetic task.',
      forecast: 'Before these attempts, a fixed 50% task-pass probability was sealed for each version. Brier loss was 0.25, tied with the constant-half baseline. This is not a learned forecast.',
      limit: 'The task supplied the invocation. This case does not measure unprompted discovery, voluntary reuse or a general release effect.',
      sources: 'studies/transcripto-record-limits/README.md · retained trial/state.json, forecast/forecast.json and score.json under ~/.local/state/sim-provider/transcripto-prospective-baseline-20261008/'
    },
    {
      id: 'markitdown', tab: '02 · Cleaner text', title: 'The output gets cleaner',
      fact: 'Three instruction cells lost escaped line breaks in the proposed output. Both versions passed.',
      task: 'Convert a synthetic XLSX release handoff into a complete Markdown table.',
      answer: 'both', answerText: 'Both versions passed the corrected task check.',
      divergenceAt: 1,
      base: { result: '1 / 1 task checks passed', path: [
        'The agent read --help, then ran the CLI with -x xlsx on the frozen workbook.',
        'The table kept recoverable action text, with escaped line breaks in three instruction cells.',
        'The agent made an awk extraction and submitted. The corrected controller check passed.'
      ]},
      proposed: { result: '1 / 1 task checks passed', path: [
        'The agent read --help, then ran the same documented CLI form on the workbook.',
        'The table flattened those line breaks to spaces. The agent made extra sed and cat commands.',
        'The agent submitted. The corrected controller check passed.'
      ]},
      divergence: 'The first meaningful tool-output divergence is the instruction-cell formatting. Later shell paths also differ, but both task checks pass. Formatting improved in this local diagnostic; completion did not.',
      check: 'Separate source-bound controller check: both passed. The earlier pair failed under a checker that rejected a documented CLI form; its original score was retained and a new seed was used here.',
      forecast: 'A fixed 50% task-pass probability was sealed for each version. Brier loss was 0.25, tied with the constant-half baseline. This is not a learned forecast.',
      limit: 'The check covered the CLI table output, not arbitrary final action-item files. One corrected local pair does not establish faster work or a broader gain.',
      sources: 'studies/markitdown-handoff/README.md · retained trial/state.json, forecast/forecast.json and score.json under ~/.local/state/sim-provider/markitdown-prospective-checker-revision-20261008/'
    },
    {
      id: 'github', tab: '03 · Both stuck', title: 'One valid page, then stuck',
      fact: 'Each arm made one valid page-one MCP call. Neither agent submitted a final inventory.',
      task: 'Inventory all forward SQL migrations in a synthetic pull request through the real GitHub MCP server.',
      answer: 'neither', answerText: 'Neither version produced a valid final inventory.',
      divergenceAt: null,
      base: { result: 'No final submission', path: [
        'The agent made one valid get_files call for page 1 and saved the MCP response.',
        'Its later Python parsing commands failed with syntax errors before processing that response.',
        'It exhausted eight model calls. No complete inventory was submitted; the controller later timed out.'
      ]},
      proposed: { result: 'No final submission', path: [
        'The agent made the same valid get_files call for page 1 and saved the response.',
        'Its later Python parsing commands failed with the same syntax problem.',
        'It exhausted eight model calls. No complete inventory was submitted; the controller later timed out.'
      ]},
      divergence: 'No meaningful agent-path divergence was observed in this pair. The source change concerns unsupported pagination arguments, but neither agent reached that boundary.',
      check: 'The retained gateway shows one valid MCP call per arm and no final submission. Controller timeout is retained as an error, not recast as an independent semantic rejection of an inventory.',
      forecast: 'A fixed 50% task-pass probability was sealed for each version. Brier loss was 0.25, tied with the constant-half baseline. This is not a learned forecast.',
      limit: 'The server was real and the API data synthetic. This null pair does not measure the proposed pagination guard, outside use or adoption.',
      sources: 'studies/github-mcp-pagination/README.md · retained base/head agent.trace.jsonl, episode.json, forecast/forecast.json and score.json under ~/.local/state/sim-provider/github-mcp-agent-baseline-20261008/'
    }
  ];
  const root = document.querySelector('#replay-story');
  const tabs = document.querySelector('#replay-cases');
  if (!root || !tabs) return;
  let retained = null;
  let retainedError = null;
  const evidencePromise = fetch('/recorded-evidence.json', {cache: 'no-store'})
    .then(response => { if (!response.ok) throw Error('HTTP ' + response.status); return response.json(); })
    .then(data => {
      if (data.kind !== 'bounded-excerpts-from-retained-local-receipts' ||
          !data.cases || !['transcripto', 'markitdown', 'github'].every(id => data.cases[id])) {
        throw Error('Unexpected evidence manifest');
      }
      retained = data;
      renderFirstPreview(firstActive);
    })
    .catch(error => { retainedError = error.message; });
  const el = (tag, content, parent, className) => {
    const item = document.createElement(tag);
    if (content) item.textContent = content;
    if (className) item.className = className;
    parent.append(item);
    return item;
  };
  let active = cases[0];
  const firstUse = document.querySelector('#first-use');
  const firstButton = document.querySelector('#first-use-start');
  const firstProgress = document.querySelector('#first-use-progress');
  const firstResult = document.querySelector('#first-use-result');
  const firstCases = document.querySelector('#first-use-cases');
  const firstPreview = document.querySelector('#first-use-preview');
  let firstActive = cases[0];
  let replaying = false;
  function previewFields(record, evidence) {
    const base = evidence.moments.base;
    const head = evidence.moments.head;
    if (record.id === 'transcripto') {
      const original = JSON.parse(base[1].records.tool_output);
      const proposed = JSON.parse(head[1].records.tool_output);
      const baseEvent = original.episodes[0].events[0];
      const headEvent = proposed.episodes[0].events[0];
      return {
        caption: base[0].records.command === head[0].records.command ? 'SAME RECORDED COMMAND · EXIT 0 IN BOTH' : 'RECORDED TOOL OUTPUT',
        base: 'status: ' + baseEvent.status,
        head: 'status: ' + headEvent.status,
        baseNote: original.warnings[0]?.includes("1 oversized record") ? "One oversized record was skipped." : original.warnings[0],
        headNote: headEvent.evidence + ' Source line ' + headEvent.result_line + '.',
        checkBase: base[2].records.controller_check.passed ? '1 / 1' : '0 / 1',
        checkHead: head[2].records.controller_check.passed ? '1 / 1' : '0 / 1',
        checkLabel: 'Separate task check'
      };
    }
    if (record.id === 'markitdown') {
      const instruction = output => output.split('\n').find(line => line.startsWith('| REL-41 '))?.split('|')[3]?.trim();
      return {
        caption: 'SAME DOCUMENTED CLI FORM · INSTRUCTION CELL',
        base: instruction(base[1].records.tool_output),
        head: instruction(head[1].records.tool_output),
        baseNote: 'Escaped line break retained in output.',
        headNote: 'The line break was flattened to a space.',
        checkBase: base[2].records.controller_check.passed ? '1 / 1' : '0 / 1',
        checkHead: head[2].records.controller_check.passed ? '1 / 1' : '0 / 1',
        checkLabel: 'Separate task check'
      };
    }
    const errorLine = row => row.records.error_output.split('\n').find(line => line.startsWith('SyntaxError:'));
    return {
      caption: 'SAME PAGE-ONE MCP CALL · NO OBSERVED DIVERGENCE',
      base: errorLine(base[1]), head: errorLine(head[1]),
      baseNote: 'No final inventory submitted.', headNote: 'No final inventory submitted.',
      checkBase: 'No submission', checkHead: 'No submission', checkLabel: 'Retained controller status'
    };
  }
  function renderFirstPreview(record) {
    if (!firstPreview) return;
    firstPreview.replaceChildren();
    const evidence = retained?.cases?.[record.id];
    if (!evidence) { el('p', retainedError ? 'Retained evidence unavailable.' : 'Reading the retained output…', firstPreview, 'small'); return; }
    const fields = previewFields(record, evidence);
    if (!fields.base || !fields.head) { el('p', 'The retained output could not be summarized. Open the full receipt below.', firstPreview, 'small'); return; }
    el('p', fields.caption, firstPreview, 'first-preview-caption');
    const split = el('div', '', firstPreview, 'first-preview-split');
    for (const [label, change, note, variant] of [['Original', fields.base, fields.baseNote, ''], ['Proposed change', fields.head, fields.headNote, ' proposed']]) {
      const arm = el('div', '', split, 'first-preview-arm' + variant);
      el('h3', label, arm);
      const headline = el('strong', '', arm);
      el('span', change, headline, 'first-preview-change');
      el('p', note, arm);
    }
    const checks = el('div', '', firstPreview, 'first-preview-check');
    el('span', fields.checkLabel, checks);
    const values = el('strong', '', checks);
    values.textContent = fields.checkBase + ' → ' + fields.checkHead;
    el('p', record.limit, firstPreview, 'first-preview-note');
  }
  function chooseFirst(record) {
    if (replaying) return;
    firstActive = record;
    document.querySelector('#first-use-title').textContent = record.title;
    document.querySelector('#first-use-task').textContent = 'Task: ' + record.task;
    for (const button of firstCases.querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.case === record.id));
    renderFirstPreview(record);
    firstButton.hidden = false;
    firstButton.textContent = 'Watch the full path →';
    firstProgress.hidden = true;
    firstResult.hidden = true;
  }
  if (firstCases) {
    for (const [index, record] of cases.entries()) {
      const button = el('button', ['Missing result', 'Cleaner text', 'Both stuck'][index], firstCases);
      button.type = 'button';
      button.dataset.case = record.id;
      button.onclick = () => chooseFirst(record);
    }
    chooseFirst(firstActive);
  }
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  function showFirstStage(record, index) {
    firstProgress.replaceChildren();
    firstProgress.hidden = false;
    firstProgress.setAttribute('aria-busy', 'true');
    el('p', 'REPLAYING SAVED RECEIPT · NO AGENT RUNNING', firstProgress, 'first-use-stage');
    el('p', (index + 1) + ' OF 3 · ' + ['TOOL CALL', 'OUTPUT AND NEXT ACTION', 'CHECKED OUTCOME'][index], firstProgress, 'first-use-stage');
    el('h3', ['What the agents did', 'What the agents saw', 'What the check found'][index], firstProgress, 'first-use-stage-title');
    const paths = el('div', '', firstProgress, 'replay-paths');
    for (const [label, arm] of [['Original', record.base], ['Proposed change', record.proposed]]) {
      const card = el('div', '', paths, 'replay-path' + (record.divergenceAt === index ? ' replay-path-diverged' : ''));
      el('h4', label, card);
      el('p', arm.path[index], card);
    }
    const rail = el('div', '', firstProgress, 'first-use-rail');
    rail.setAttribute('aria-label', 'Stage ' + (index + 1) + ' of 3');
    [0, 1, 2].forEach(i => {
      const track = el('span', '', rail, i < index ? 'done' : i === index ? 'active' : '');
      if (i === index) el('i', '', track, 'first-use-rail-fill');
    });
    if (index === 0) firstProgress.scrollIntoView({behavior:'smooth', block:'center'});
  }
  function showFirstResult(record) {
    firstProgress.hidden = true;
    firstProgress.removeAttribute('aria-busy');
    firstResult.hidden = false;
    firstResult.replaceChildren();
    el('p', 'RECORDED RESULT · ONE ATTEMPT PER VERSION', firstResult, 'first-use-stage');
    el('h3', record.answerText, firstResult);
    const outcomes = el('div', '', firstResult, 'first-use-outcome');
    for (const [label, value] of [['Original', record.base.result], ['Proposed change', record.proposed.result]]) {
      const card = el('article', '', outcomes); el('strong', label, card); el('p', value, card);
    }
    const trace = el('div', '', firstResult, 'first-use-trace');
    el('strong', record.divergenceAt === null ? 'No decisive path divergence observed' : 'Decisive recorded trace', trace);
    el('p', record.divergence, trace);
    el('p', record.check, firstResult);
    el('p', record.limit, firstResult, 'small');
    const receipt = retained?.cases?.[record.id];
    if (receipt) {
      const proof = el('details', '', firstResult, 'replay-source-detail');
      el('summary', 'Inspect the decisive trace, task check and source hashes', proof);
      for (const [i, row] of [receipt.moments.base[1], receipt.moments.head[1], receipt.moments.base[2], receipt.moments.head[2]].entries()) {
        const item = el('div', '', proof, 'replay-source-item');
        el('strong', ['Original output', 'Proposed output', 'Original check', 'Proposed check'][i], item);
        el('p', row.source + ' · SHA-256 ' + row.sha256, item, 'replay-sources');
        el('pre', JSON.stringify(row.records, null, 2), item);
      }
    }
    el('p', 'Source: ' + record.sources, firstResult, 'first-use-provenance');
    const actions = el('div', '', firstResult, 'first-use-actions');
    const build = el('button', 'See what my tool would need →', actions); build.type = 'button';
    build.onclick = () => {
      const entry = document.querySelector('#own-tool-entry'); entry.hidden = false;
      entry.scrollIntoView({behavior:'smooth', block:'start'});
    };
    const explore = el('button', 'Explore more recorded cases', actions); explore.type = 'button';
    explore.onclick = () => {
      const panel = document.querySelector('#more-cases-panel'); panel.hidden = false;
      panel.scrollIntoView({behavior:'smooth'});
    };
    firstResult.scrollIntoView({behavior:'smooth', block:'start'});
  }
  const ownContinue = document.querySelector('#own-tool-continue');
  if (ownContinue) ownContinue.onclick = () => {
    const path = document.querySelector('#own-tool-path').value.trim();
    const status = document.querySelector('#own-tool-status');
    if (!path.startsWith('/')) { status.textContent = 'Enter an absolute path to a local Git repository. A GitHub URL cannot start a comparison here.'; return; }
    status.textContent = 'Path copied into local setup. You still need committed versions, a task, an evaluator and a private session token.';
    document.querySelector('#source-repo').value = path;
    document.querySelector('#workspace-after-sample').hidden = false;
    const builder = document.querySelector('#create-panel'); builder.open = true;
    builder.scrollIntoView({behavior:'smooth', block:'start'});
  };
  if (firstUse && firstButton && firstProgress && firstResult) firstButton.onclick = async () => {
    const record = firstActive;
    replaying = true;
    for (const button of firstCases.querySelectorAll('button')) button.disabled = true;
    firstButton.disabled = true;
    firstButton.textContent = 'Reading retained case…';
    firstProgress.hidden = false;
    firstProgress.setAttribute('aria-busy', 'true');
    firstProgress.textContent = 'Reading the retained local receipt. No agent is running.';
    await evidencePromise;
    if (!retained?.cases?.[record.id]) {
      firstProgress.removeAttribute('aria-busy');
      firstProgress.textContent = 'The retained receipt could not be read' + (retainedError ? ': ' + retainedError : '.') + ' Try again when the local evidence is available.';
      firstButton.disabled = false; firstButton.textContent = 'Retry the first case →';
      replaying = false;
      for (const button of firstCases.querySelectorAll('button')) button.disabled = false;
      return;
    }
    for (let i = 0; i < 3; i++) { showFirstStage(record, i); await pause(1200); }
    showFirstResult(record);
    firstButton.hidden = true;
    firstButton.disabled = false;
    replaying = false;
    for (const button of firstCases.querySelectorAll('button')) button.disabled = false;
  };
  function sourceDetails(parent, title, rows, labels) {
    const details = el('details', '', parent, 'replay-source-detail');
    el('summary', title, details);
    for (const [index, row] of rows.entries()) {
      const item = el('div', '', details, 'replay-source-item');
      el('strong', labels[index], item);
      el('p', row.source + ' · SHA-256 ' + row.sha256, item, 'replay-sources');
      el('pre', JSON.stringify(row.records, null, 2), item);
    }
  }
  function select(record) {
    active = record;
    for (const button of tabs.querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.case === record.id));
    root.replaceChildren();
    const fact = document.querySelector('#research-fact');
    fact.replaceChildren(); el('strong', 'FROM THE RETAINED LOCAL RECEIPT', fact); el('p', record.fact, fact);
    fact.classList.remove('fact-arrive'); void fact.offsetWidth; fact.classList.add('fact-arrive');
    el('p', 'FROZEN TASK', root, 'replay-label');
    el('h3', record.title, root);
    el('p', record.task, root);
    el('p', 'Which version passed the task check?', root, 'replay-question');
    const choices = el('div', '', root, 'replay-choices');
    for (const [value, label] of [['original', 'Original only'], ['proposed', 'Proposed only'], ['both', 'Both'], ['neither', 'Neither']]) {
      const button = el('button', label, choices);
      button.type = 'button';
      button.onclick = () => reveal(record, value);
    }
  }
  function reveal(record, guess) {
    if (active !== record) return;
    const old = root.querySelector('.replay-reveal');
    if (old) old.remove();
    for (const button of root.querySelectorAll('.replay-choices button')) button.disabled = true;
    const panel = el('div', '', root, 'replay-reveal');
    el('p', (guess === record.answer ? 'You called it. ' : 'The retained result: ') + record.answerText, panel, 'replay-answer');
    const stages = el('div', '', panel, 'replay-stages');
    stages.setAttribute('role', 'group');
    stages.setAttribute('aria-label', 'Recorded path moments');
    const moment = el('div', '', panel, 'replay-moment');
    moment.id = 'replay-moment';
    moment.setAttribute('role', 'region');
    moment.setAttribute('aria-label', 'Current recorded moment');
    moment.setAttribute('aria-live', 'polite');
    const forecast = el('details', '', panel, 'replay-forecast');
    el('summary', 'Then inspect the separately sealed forecast', forecast);
    el('p', record.forecast, forecast);
    const forecastRecords = el('div', '', forecast);
    el('p', record.limit, panel, 'small');
    el('p', 'Source: ' + record.sources, panel, 'replay-sources');
    const next = el('button', 'Build a comparison with my tool', panel);
    next.type = 'button';
    next.onclick = () => { const entry = document.querySelector('#own-tool-entry'); entry.hidden = false; entry.scrollIntoView({behavior:'smooth'}); };
    const labels = ['1 · Tool call', '2 · Output and next action', '3 · Checked result'];
    let currentIndex = 0;
    const stageButtons = labels.map((label, index) => {
      const button = el('button', label, stages);
      button.type = 'button';
      button.setAttribute('aria-controls', moment.id);
      button.onclick = () => showMoment(index);
      button.onkeydown = event => {
        if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
        stageButtons[nextIndex].focus();
        showMoment(nextIndex);
      };
      return button;
    });
    function showMoment(index) {
      currentIndex = index;
      for (const [i, button] of stageButtons.entries()) button.setAttribute('aria-pressed', String(i === index));
      moment.replaceChildren();
      el('p', 'MOMENT ' + (index + 1) + ' OF 3 · ' + labels[index].split(' · ')[1].toUpperCase(), moment, 'replay-label');
      const paths = el('div', '', moment, 'replay-paths');
      for (const [name, arm] of [['ORIGINAL', record.base], ['PROPOSED CHANGE', record.proposed]]) {
        const card = el('div', '', paths, 'replay-path' + (record.divergenceAt === index ? ' replay-path-diverged' : ''));
        el('h3', name, card);
        if (index === 2) el('strong', arm.result, card);
        el('p', arm.path[index], card);
      }
      if (index === record.divergenceAt || record.divergenceAt === null) {
        const divergence = el('div', '', moment, 'replay-callout' + (record.divergenceAt === null ? ' replay-null' : ''));
        el('h3', record.divergenceAt === null ? 'NO OBSERVED PATH DIVERGENCE' : 'FIRST MEANINGFUL DIVERGENCE', divergence);
        el('p', record.divergence, divergence);
      }
      if (index === 2) {
        const checked = el('div', '', moment, 'replay-callout');
        el('h3', 'CHECKED OUTCOME', checked);
        el('p', record.check, checked);
      }
      if (retained?.cases[record.id]) {
        const matched = retained.cases[record.id];
        sourceDetails(moment, 'Inspect retained fields and source hashes',
          [matched.moments.base[index], matched.moments.head[index]], ['Original receipt', 'Proposed receipt']);
        forecastRecords.replaceChildren();
        sourceDetails(forecastRecords, 'Inspect sealed forecast and score fields', matched.forecast, ['Forecast receipt', 'Scored outcomes']);
      } else {
        el('p', retainedError ? 'Retained evidence unavailable: ' + retainedError : 'Loading retained evidence…', moment, 'small');
      }
      forecast.hidden = index !== 2;
    }
    showMoment(0);
    evidencePromise.then(() => { if (active === record && panel.isConnected) showMoment(currentIndex); });
  }
  for (const record of cases) {
    const button = el('button', record.tab, tabs);
    button.type = 'button';
    button.dataset.case = record.id;
    button.onclick = () => select(record);
  }
  select(active);
})();
