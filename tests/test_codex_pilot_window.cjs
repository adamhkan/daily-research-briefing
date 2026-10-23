const assert = require('node:assert/strict');
const test = require('node:test');
const config = require('../config/codex-pilot.json');
const { apiRunDecision, validatePilotConfig } = require('../.github/scripts/codex-pilot-window.cjs');

function decision(at, candidate = config, now = at) {
  return apiRunDecision(at, candidate, now);
}

test('pause all three pilot report dates and resume after the inclusive end', () => {
  for (const date of ['2026-10-23', '2026-10-24', '2026-10-25']) {
    assert.equal(decision(`${date}T12:30:00Z`).apiEnabled, false);
  }
  assert.equal(decision('2026-10-22T12:30:00Z').apiEnabled, true);
  assert.equal(decision('2026-10-26T12:30:00Z').apiEnabled, true);
});

test('window boundaries use Eastern report date rather than UTC date', () => {
  assert.equal(decision('2026-10-23T03:59:59Z').apiEnabled, true);
  assert.equal(decision('2026-10-23T04:00:00Z').apiEnabled, false);
  assert.equal(decision('2026-10-26T03:59:59Z').apiEnabled, false);
  assert.equal(decision('2026-10-26T04:00:00Z').apiEnabled, true);
});

test('original pilot date remains paused on later reruns and preserves report dates', () => {
  const result = decision('2026-10-23T23:30:00Z', config, '2026-10-26T12:30:00Z');
  assert.equal(result.reportDate, '2026-10-23');
  assert.equal(result.submissionDate, '2026-10-22');
  assert.equal(result.apiEnabled, false);
});

test('old failed runs cannot spend during current Eastern pilot dates', () => {
  const result = decision('2026-10-22T12:30:00Z', config, '2026-10-24T12:30:00Z');
  assert.equal(result.apiEnabled, false);
  assert.equal(result.reportDate, '2026-10-22');
  assert.equal(result.submissionDate, '2026-10-21');
  assert.equal(decision('2026-10-22T12:30:00Z', config, '2026-10-26T12:30:00Z').apiEnabled, true);
  assert.equal(decision('2026-10-26T12:30:00Z', config, '2026-10-26T12:30:00Z').apiEnabled, true);
});

test('explicit pause opt-out enables the normal API workflow', () => {
  assert.equal(decision('2026-10-24T12:30:00Z', { ...config, pause_paid_api: false }).apiEnabled, true);
});

test('invalid configuration fails instead of implicitly enabling paid generation', () => {
  for (const candidate of [null, [], {},
    { ...config, start_date: '2026-02-30' },
    { ...config, end_date: '2026-10-22' },
    { ...config, timezone: 'UTC' },
    { ...config, pause_paid_api: 'true' },
    { ...config, publish: null },
    { ...config, hour: 24 },
    { ...config, minute: -1 },
    { ...config, max_requests: 0 },
    { ...config, output_root: '../reports' },
    { ...config, output_root: 'reports/pilot' },
    { ...config, output_root: '/tmp/pilot' },
  ]) {
    assert.throws(() => validatePilotConfig(candidate));
  }
  assert.throws(() => apiRunDecision('not-a-date', config, '2026-10-22T12:30:00Z'));
  assert.throws(() => apiRunDecision('2026-10-22T12:30:00Z', config, 'not-a-date'));
});
