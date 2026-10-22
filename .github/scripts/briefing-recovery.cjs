const WORKFLOW_ID = 'daily-robotics-briefing.yml';
const RETRY_DELAY_MS = 30 * 60 * 1000;
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

// Reruns keep the original run's creation time, even across Eastern midnight.
function reportDates(createdAt) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(createdAt));
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  const reportDate = `${values.year}-${values.month}-${values.day}`;
  const previousDay = new Date(`${reportDate}T00:00:00Z`);
  previousDay.setUTCDate(previousDay.getUTCDate() - 1);
  return { reportDate, submissionDate: previousDay.toISOString().slice(0, 10) };
}

function eligible(run, now) {
  const age = now - Date.parse(run.created_at);
  const failedFor = now - Date.parse(run.updated_at);
  return ['schedule', 'workflow_dispatch'].includes(run.event)
    && run.head_branch === 'main'
    && run.status === 'completed'
    && ['failure', 'timed_out'].includes(run.conclusion)
    && run.run_attempt === 1
    && age >= 0
    && failedFor >= RETRY_DELAY_MS && failedFor < MAX_AGE_MS;
}

async function retryBriefing({ github, context, core, now = Date.now() }) {
  const repo = context.repo;
  const { data } = await github.rest.actions.listWorkflowRuns({
    ...repo, workflow_id: WORKFLOW_ID, branch: 'main', per_page: 100,
  });
  const runs = data.workflow_runs.filter(run =>
    ['schedule', 'workflow_dispatch'].includes(run.event));
  // An older failure must not overwrite a newer successful or active briefing.
  runs.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id);
  const latest = runs[0];
  if (!latest || !eligible(latest, now)) {
    core.info('No recent failed briefing is eligible for its one automatic retry.');
    return;
  }

  // Recheck in case someone manually reran it while this check was starting.
  const { data: current } = await github.rest.actions.getWorkflowRun({ ...repo, run_id: latest.id });
  if (!eligible(current, now)) {
    core.info('The briefing has changed state; skipping the retry.');
    return;
  }
  await github.rest.actions.reRunWorkflowFailedJobs({ ...repo, run_id: current.id });
  await core.summary.addHeading('Briefing retry requested')
    .addLink(`Run ${current.id}: attempt 2 of 2`, current.html_url)
    .addRaw('\nOnly failed jobs and their dependent jobs will rerun.\n')
    .write();
  core.info(`Requested the one automatic retry for ${current.html_url}`);
}

module.exports = { reportDates, retryBriefing };
