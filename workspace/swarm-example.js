// One recorded, real-model case. This draws paths from observed commands only.
(() => {
  const root = document.querySelector('#swarm-example');
  if (!root) return;
  const svg = document.querySelector('#swarm-burst');
  const field = document.querySelector('#swarm-field');
  const lanes = document.querySelector('#swarm-lanes');
  const selected = document.querySelector('#swarm-selected');
  const ns = 'http://www.w3.org/2000/svg';
  let runs = [];
  const node = (tag, value, parent) => {
    const element = document.createElement(tag);
    element.textContent = value;
    parent.append(element);
    return element;
  };
  const svgNode = (tag, attributes, parent) => {
    const element = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
    parent.append(element);
    return element;
  };
  function select(index) {
    const run = runs[index];
    if (!run) return;
    for (const path of svg.querySelectorAll('[data-run]'))
      path.classList.toggle('picked', Number(path.dataset.run) === index);
    for (const dot of field.querySelectorAll('[data-run]'))
      dot.classList.toggle('picked', Number(dot.dataset.run) === index);
    for (const button of lanes.querySelectorAll('button[data-run]'))
      button.setAttribute('aria-pressed', String(Number(button.dataset.run) === index));
    selected.replaceChildren();
    node('strong', (run.arm === 'before' ? 'Before' : 'After') + ' · agent ' + String(run.seed).slice(-3) +
      ' · ' + (run.task_passed ? 'finished the task' : 'did not finish'), selected);
    node('p', run.calls + ' model calls · ' + run.seconds + ' seconds · ' + run.status, selected);
    const list = node('ol', '', selected);
    for (const step of run.steps) node('li', step.command + ' · exit ' + step.exit, list);
  }
  function render(data) {
    runs = data.runs;
    field.replaceChildren();
    for (let call = 1; call <= 8; call++) {
      const x = 40 + call * 50;
      svgNode('line', {x1: x, y1: 17, x2: x, y2: 124, class: 'grid'}, field);
      svgNode('text', {x, y: 140, 'text-anchor': 'middle'}, field).textContent = String(call);
    }
    svgNode('line', {x1: 24, y1: 74, x2: 480, y2: 74, class: 'pass-line'}, field);
    svgNode('text', {x: 24, y: 13}, field).textContent = 'Passed';
    svgNode('text', {x: 24, y: 91}, field).textContent = 'Stopped';
    const occupied = new Map();
    runs.forEach((run, index) => {
      const key = `${run.calls}:${run.task_passed}:${run.arm}`;
      const slot = occupied.get(key) || 0;
      occupied.set(key, slot + 1);
      const x = 40 + run.calls * 50 + (slot % 3 - 1) * 12;
      const y = run.task_passed ? 59 - Math.floor(slot / 3) * 12 :
        101 + Math.floor(slot / 3) * 12;
      const dot = svgNode('circle', {cx: x, cy: y, r: 5, class: run.arm,
        'data-run': index, tabindex: 0, role: 'button'}, field);
      svgNode('title', {}, dot).textContent = (run.arm === 'before' ? 'Before' : 'After') +
        ' agent ' + String(run.seed).slice(-3) + ': ' + run.calls + ' calls, ' +
        (run.task_passed ? 'passed' : 'stopped');
      dot.addEventListener('click', () => select(index));
      dot.addEventListener('keydown', event => { if (event.key === 'Enter') select(index); });
    });
    svg.replaceChildren();
    for (const y of [42, 81, 120, 159, 198]) svgNode('line', {x1: 18, y1: y, x2: 505, y2: y, class: 'axis'}, svg);
    svgNode('circle', {cx: 20, cy: 120, r: 5, fill: '#22121c'}, svg);
    runs.forEach((run, index) => {
      const targetY = 24 + index * 10;
      let y = 120;
      const points = [`M 20 ${y.toFixed(1)}`];
      run.steps.forEach((step, stepIndex) => {
        y = 120 + (targetY - 120) * (stepIndex + 1) / run.steps.length +
          (step.exit === 0 ? 0 : 7);
        points.push(`L ${42 + (stepIndex + 1) * 51} ${y.toFixed(1)}`);
      });
      const lastX = 42 + run.steps.length * 51;
      const path = svgNode('path', {d: points.join(' '), class: 'swarm-path ' + run.arm,
                                     'data-run': index, tabindex: 0}, svg);
      svgNode('title', {}, path).textContent = (run.arm === 'before' ? 'Before' : 'After') +
        ' agent ' + String(run.seed).slice(-3) + ': ' + (run.task_passed ? 'finished' : 'stopped');
      path.addEventListener('click', () => select(index));
      path.addEventListener('keydown', event => { if (event.key === 'Enter') select(index); });
      const endpoint = svgNode('circle', {cx: lastX, cy: y.toFixed(1), r: 3.5,
        class: 'end ' + run.arm + (run.task_passed ? '' : ' failed'), 'data-run': index, tabindex: 0}, svg);
      endpoint.addEventListener('click', () => select(index));
      endpoint.addEventListener('keydown', event => { if (event.key === 'Enter') select(index); });
    });
    lanes.replaceChildren();
    const seeds = [...new Set(runs.map(run => run.seed))].sort((a, b) => a - b);
    seeds.forEach((seed, index) => {
      const row = node('div', '', lanes); row.className = 'swarm-lane';
      node('span', String(index + 1).padStart(2, '0'), row);
      for (const arm of ['before', 'after']) {
        const runIndex = runs.findIndex(run => run.seed === seed && run.arm === arm);
        const run = runs[runIndex];
        const button = node('button', '', row);
        button.type = 'button'; button.dataset.run = String(runIndex);
        button.className = arm + (run.task_passed ? '' : ' fail');
        button.setAttribute('aria-label', arm + ' agent ' + String(seed).slice(-3) +
          ': ' + (run.task_passed ? 'finished' : 'did not finish') + ', ' + run.calls + ' calls');
        button.setAttribute('aria-pressed', 'false');
        for (let call = 0; call < run.calls; call++) node('i', '', button);
        node('em', run.task_passed ? 'finished' : 'stopped', button);
        button.onclick = () => select(runIndex);
      }
    });
    document.querySelector('#swarm-scope').textContent = data.scope + ' Source: ' + data.pr +
      '. Before ' + data.before + '; after ' + data.after + '. ' + data.inference +
      '; tool execution in ' + data.tool_execution + '. Provider listed-rate estimate $' +
      data.cost_list_price_estimate_usd + ', not a bill. Horizontal graph steps are commands, not elapsed time.';
    select(runs.findIndex(run => run.arm === 'before' && !run.task_passed));
  }
  window.addEventListener('retained-swarm', event => {
    const trial = event.detail;
    const episodes = trial?.state?.episodes;
    if (trial?.state?.status !== 'complete' || !Array.isArray(episodes) || !episodes.length) return;
    const perArm = arm => episodes.filter(run => run.arm === arm);
    const count = arm => perArm(arm).filter(run => run.completed === true).length + '/' + perArm(arm).length;
    document.querySelector('#swarm-title').textContent = trial.import?.label || trial.contract.name;
    document.querySelector('#swarm-description').textContent = 'Before: ' + count('base') +
      ' finished. After: ' + count('head') + ' finished. These are retained attempts, not a new run.';
    document.querySelector('#swarm-task-note').textContent = 'Frozen task: ' + trial.contract.task;
    root.querySelector('.swarm-top span').textContent = trial.state.provider_runtime_verified ?
      'RECORDED · REAL NEMOTRON · LOCAL SANDBOX' : 'RECORDED · LOCAL · PROVIDER NOT VERIFIED';
    field.setAttribute('aria-label', episodes.length + ' retained attempts by model calls and task check');
    svg.setAttribute('aria-label', episodes.length + ' retained command paths');
    render({
      runs: episodes.map(run => ({arm: run.arm === 'base' ? 'before' : 'after', seed: run.seed,
        task_passed: run.completed === true, calls: run.model_calls, seconds: run.wall_seconds,
        status: run.status, steps: (run.shell_trace || []).map(step =>
          ({command: step.command, exit: step.returncode}))})),
      scope: (trial.import?.note || 'Author-made task and separate artifact check.') +
        ' Replay geometry is illustrative; command order and final verdict come from the saved trace.',
      pr: trial.publicPr?.url || trial.contract.name,
      before: trial.contract.arms.base.commit, after: trial.contract.arms.head.commit,
      inference: trial.state.model?.id || 'model identity not recorded', tool_execution: 'local Docker',
      cost_list_price_estimate_usd: trial.state.cost?.controller_account?.accounted_usd ?? 'unknown'
    });
    if (!root.querySelector('#swarm-review-link')) {
      const link = node('a', 'Review the result and release choice ↓', root);
      link.id = 'swarm-review-link'; link.href = '#glance';
    }
  });
  document.querySelector('#swarm-replay').onclick = () => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    for (const [index, path] of [...svg.querySelectorAll('.swarm-path')].entries()) {
      const length = path.getTotalLength();
      path.style.transition = 'none';
      path.style.strokeDasharray = String(length);
      path.style.strokeDashoffset = String(length);
      path.getBoundingClientRect();
      path.style.transition = `stroke-dashoffset 850ms ease ${index * 65}ms`;
      path.style.strokeDashoffset = '0';
    }
  };
  fetch('/swarm-example.json').then(response => {
    if (!response.ok) throw Error('Recorded example unavailable.');
    return response.json();
  }).then(render).catch(() => {
    selected.textContent = 'Recorded example unavailable. The PR form above still works.';
  });
})();
