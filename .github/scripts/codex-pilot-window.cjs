const { reportDates } = require('./briefing-recovery.cjs');

function validDate(value) {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function validatePilotConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('Codex pilot configuration must be an object');
  }
  if (!validDate(config.start_date) || !validDate(config.end_date)
      || config.start_date > config.end_date) {
    throw new Error('Codex pilot requires an ordered, inclusive start_date/end_date window');
  }
  if (config.timezone !== 'America/New_York') {
    throw new Error('Codex pilot report dates must use America/New_York');
  }
  if (!Number.isInteger(config.hour) || config.hour < 0 || config.hour > 23
      || !Number.isInteger(config.minute) || config.minute < 0 || config.minute > 59) {
    throw new Error('Codex pilot requires a valid local hour/minute');
  }
  if (typeof config.pause_paid_api !== 'boolean' || typeof config.publish !== 'boolean') {
    throw new Error('Codex pilot pause_paid_api and publish must be booleans');
  }
  if (!Number.isInteger(config.max_requests) || config.max_requests < 1) {
    throw new Error('Codex pilot max_requests must be a positive integer');
  }
  if (typeof config.output_root !== 'string' || !config.output_root
      || config.output_root.startsWith('/') || config.output_root.split(/[\\/]/).includes('..')
      || /^reports(?:[\\/]|$)/.test(config.output_root)) {
    throw new Error('Codex pilot output_root must be a separate relative path outside reports');
  }
  return config;
}

// Preserve original report dates, but also block pre-pilot run retries while
// the pilot is active. A pilot-day run remains paused after the window ends.
function apiRunDecision(createdAt, rawConfig, now = new Date().toISOString()) {
  const config = validatePilotConfig(rawConfig);
  if (typeof createdAt !== 'string' || !Number.isFinite(Date.parse(createdAt))) {
    throw new Error('A valid original workflow created_at is required');
  }
  if (typeof now !== 'string' || !Number.isFinite(Date.parse(now))) {
    throw new Error('A valid current time is required');
  }
  const { reportDate, submissionDate } = reportDates(createdAt);
  const currentDate = reportDates(now).reportDate;
  const inWindow = date => date >= config.start_date && date <= config.end_date;
  const paused = config.pause_paid_api && (inWindow(reportDate) || inWindow(currentDate));
  return {
    apiEnabled: !paused,
    reportDate,
    submissionDate,
    reason: paused
      ? `Paid generation paused for Codex pilot dates ${config.start_date} through ${config.end_date} (original report ${reportDate}; current Eastern date ${currentDate})`
      : 'Paid generation enabled outside the pilot pause window',
  };
}

module.exports = { validatePilotConfig, apiRunDecision };
