const { test } = require('node:test');
const assert = require('node:assert/strict');
const { reportDates, retryBriefing } = require('../.github/scripts/briefing-recovery.cjs');

const NOW = Date.parse('2026-10-22T12:00:00Z');
function failedRun(overrides = {}) {
  return {
    id: 123, event: 'schedule', head_branch: 'main', status: 'completed',
    conclusion: 'failure', run_attempt: 1,
    created_at: '2026-10-22T11:15:00Z', updated_at: '2026-10-22T11:30:00Z',
    html_url: 'https://github.com/example/briefing/actions/runs/123',
    ...overrides,
  };
}

async function check(runs, current = runs[0], rerunError) {
  const calls = [];
  const summary = {
    addHeading() { return this; }, addLink() { return this; }, addRaw() { return this; },
    async write() { calls.push(['summary']); },
  };
  const github = { rest: { actions: {
    async listWorkflowRuns(args) { calls.push(['list', args]); return { data: { workflow_runs: runs } }; },
    async getWorkflowRun(args) { calls.push(['get', args]); return { data: current }; },
    async reRunWorkflowFailedJobs(args) {
      calls.push(['rerun', args]);
      if (rerunError) throw rerunError;
    },
  } } };
  await retryBriefing({ github, context: { repo: { owner: 'example', repo: 'briefing' } },
    core: { info() {}, summary }, now: NOW });
  return calls;
}

test('retry a runner allocation failure at the 30-minute boundary', async () => {
  const calls = await check([failedRun()]);
  assert.deepEqual(calls.map(([name]) => name), ['list', 'get', 'rerun', 'summary']);
  assert.deepEqual(calls[0][1], { owner: 'example', repo: 'briefing',
    workflow_id: 'daily-robotics-briefing.yml', branch: 'main', per_page: 100 });
  assert.deepEqual(calls[2][1], { owner: 'example', repo: 'briefing', run_id: 123 });
});

test('wait for 30 minutes after completion, not after the run started', async () => {
  const calls = await check([failedRun({ updated_at: '2026-10-22T11:30:01Z' })]);
  assert.deepEqual(calls.map(([name]) => name), ['list']);
});

test('a timed-out manually dispatched run is retried', async () => {
  const calls = await check([failedRun({ event: 'workflow_dispatch', conclusion: 'timed_out' })]);
  assert.ok(calls.some(([name]) => name === 'rerun'));
});

test('a long runner wait does not make a freshly recorded failure too old', async () => {
  const calls = await check([failedRun({ created_at: '2026-10-21T10:00:00Z' })]);
  assert.ok(calls.some(([name]) => name === 'rerun'));
});

for (const [reason, overrides] of [
  ['successful', { conclusion: 'success' }],
  ['cancelled', { conclusion: 'cancelled' }],
  ['running', { status: 'in_progress', conclusion: null }],
  ['queued', { status: 'queued', conclusion: null }],
  ['already retried automatically or manually', { run_attempt: 2 }],
  ['on a different branch', { head_branch: 'experiment' }],
  ['triggered by a different event', { event: 'push' }],
  ['failed 24 hours ago', {
    created_at: '2026-10-21T11:15:00Z', updated_at: '2026-10-21T12:00:00Z',
  }],
]) {
  test(`skip a run that is ${reason}`, async () => {
    const calls = await check([failedRun(overrides)]);
    assert.deepEqual(calls.map(([name]) => name), ['list']);
  });
}

for (const status of ['completed', 'in_progress', 'queued']) {
  test(`a newer ${status} run supersedes an older failure`, async () => {
    const newer = failedRun({ id: 124, created_at: '2026-10-22T11:45:00Z',
      updated_at: '2026-10-22T11:50:00Z', status,
      conclusion: status === 'completed' ? 'success' : null });
    const calls = await check([failedRun(), newer]);
    assert.deepEqual(calls.map(([name]) => name), ['list']);
  });
}

test('use run ID to disambiguate runs created in the same second', async () => {
  const calls = await check([failedRun(), failedRun({ id: 124, conclusion: 'success' })]);
  assert.deepEqual(calls.map(([name]) => name), ['list']);
});

test('skip when a manual rerun starts during the check', async () => {
  const calls = await check([failedRun()], failedRun({ run_attempt: 2, status: 'queued' }));
  assert.deepEqual(calls.map(([name]) => name), ['list', 'get']);
});

test('no previous daily run is a successful no-op', async () => {
  const calls = await check([]);
  assert.deepEqual(calls.map(([name]) => name), ['list']);
});

test('surface a GitHub API rejection instead of reporting a successful retry', async () => {
  await assert.rejects(check([failedRun()], undefined, new Error('Forbidden')), /Forbidden/);
});

test('original run dates are stable across midnight and year boundaries', () => {
  assert.deepEqual(reportDates('2026-01-01T04:30:00Z'), {
    reportDate: '2025-12-31', submissionDate: '2025-12-30',
  });
  assert.deepEqual(reportDates('2026-01-01T05:30:00Z'), {
    reportDate: '2026-01-01', submissionDate: '2025-12-31',
  });
});

test('Eastern daylight saving boundaries preserve the previous calendar day', () => {
  for (const createdAt of ['2026-03-08T07:30:00Z', '2026-11-01T06:30:00Z']) {
    const monthDay = createdAt.slice(0, 10);
    assert.deepEqual(reportDates(createdAt), {
      reportDate: monthDay,
      submissionDate: monthDay === '2026-03-08' ? '2026-03-07' : '2026-10-31',
    });
  }
});
