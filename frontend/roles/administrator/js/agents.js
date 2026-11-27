// Administrator module — Agent Control.
// Lists the ten planned agents and wires the Data Collection Agent controls.
// No agent is executed, no schedule is created and no AI model is configured.
// The existing Invention Profiling Agent is only described here: it is not
// invoked, configured or modified from this module.
(function () {
  'use strict';
  const {el, badge, ncButton, emptyRow, onReady} = window.AdminUI;

  const AGENTS = [
    {id: 'orchestrator', name: 'Orchestrator Agent',
     purpose: 'Coordinates the other agents and the order in which they run.'},
    {id: 'profiling', name: 'Invention Profiling Agent', existing: true,
     purpose: 'Builds invention profiles from innovator documents (Innovator module).'},
    {id: 'collection', name: 'Data Collection Agent', featured: true,
     purpose: 'Discovers organizations and collects public business information as drafts for approval.'},
    {id: 'market', name: 'Market Signal Agent',
     purpose: 'Tracks market and industry signals relevant to inventions.'},
    {id: 'matching', name: 'Matching & Scoring Agent',
     purpose: 'Scores fit between inventions and organizations.'},
    {id: 'explanation', name: 'Explanation Agent',
     purpose: 'Explains why a match was proposed, with evidence.'},
    {id: 'risk', name: 'Risk & Compliance Agent',
     purpose: 'Flags confidentiality, conflict and compliance risks.'},
    {id: 'outreach', name: 'Outreach Drafting Agent',
     purpose: 'Drafts outreach messages for staff review.'},
    {id: 'engagement', name: 'Engagement Tracking Agent',
     purpose: 'Tracks partner engagement stages and follow-ups.'},
    {id: 'learning', name: 'Learning Agent',
     purpose: 'Learns from reviewer decisions to improve future suggestions.'}
  ];

  function statusBadge(agent) {
    return agent.existing ? badge('Exists — managed in Innovator module', 'info')
                          : badge('Planned — not connected', 'neutral');
  }

  function renderOverviewRows() {
    const tbody = document.getElementById('agentStatusRows');
    if (!tbody) return;
    tbody.replaceChildren(...AGENTS.map(agent => el('tr', {},
      el('th', {scope: 'row', text: agent.name}),
      el('td', {}, statusBadge(agent)),
      el('td', {class: 'unavailable', text: 'Not available'}),
      el('td', {class: 'unavailable', text: 'Not available'}))));
  }

  function renderAgentGrid() {
    const grid = document.getElementById('agentGrid');
    if (!grid) return;
    grid.replaceChildren(...AGENTS.map((agent, index) => {
      const headingId = 'agent-' + agent.id + '-h';
      return el('li', {class: 'agent-card' + (agent.featured ? ' featured' : ''),
                       'aria-labelledby': headingId},
        el('span', {class: 'agent-num', text: 'Agent ' + (index + 1)}),
        el('h3', {id: headingId, text: agent.name}),
        el('p', {text: agent.purpose}),
        el('div', {}, statusBadge(agent)),
        agent.existing
          ? el('p', {class: 'small', text: 'This agent already exists. It is not invoked, configured ' +
                                         'or modified from the Administrator module.'})
          : agent.featured
            ? el('a', {href: '#collection-h', class: 'btn small', text: 'Open detailed controls'})
            : el('div', {class: 'toolbar', style: 'margin:4px 0 0'},
                el('span', {'data-requires': 'agents.collection.execute'}, ncButton('Run')),
                el('span', {'data-requires': 'agents.collection.history'}, ncButton('View history'))));
    }));
  }

  // Schedule form: the enable switch only toggles the other fields locally.
  function wireSchedule() {
    const enable = document.getElementById('sch-enabled');
    if (!enable) return;
    const fields = ['sch-frequency', 'sch-day', 'sch-time'].map(id => document.getElementById(id));
    const sync = () => {
      for (const f of fields) f.disabled = !enable.checked;
      document.getElementById('sch-state').textContent = enable.checked
        ? 'Enabled in this form only — no schedule has been created.'
        : 'Automatic collection is off in this form.';
    };
    enable.addEventListener('change', sync);
    sync();
  }

  function renderEmptyTables() {
    const history = document.getElementById('runHistoryRows');
    if (history) emptyRow(history, 6, 'No executions recorded',
      'Data Collection Agent runs will appear here once the agent is connected.');
    const errors = document.getElementById('errorRows');
    if (errors) emptyRow(errors, 4, 'No collection errors',
      'Errors from failed collection jobs will appear here.');
  }

  onReady(() => {
    renderOverviewRows();
    renderAgentGrid();
    wireSchedule();
    renderEmptyTables();
  });

  window.AdminAgents = AGENTS.map(a => ({...a}));
})();
