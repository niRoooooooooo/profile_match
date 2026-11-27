// Administrator module — Data Approvals and Approval Review.
// No drafts are loaded and no decision is recorded. The approved organization
// profile is never modified from this module.
(function () {
  'use strict';
  const {el, badge, emptyRow, onReady} = window.AdminUI;

  const SOURCE_TYPES = ['Official company website', 'Government database', 'Patent database',
                        'Industry directory', 'Investor website', 'Financial report',
                        'News publication', 'Public API', 'Employee-uploaded document'];

  const CATEGORIES = [
    {id: 'new', label: 'New profile drafts',
     text: 'Drafts for organizations that do not have an approved profile yet.'},
    {id: 'revision', label: 'Revision drafts',
     text: 'Proposed changes to an existing approved profile, from weekly collection or uploaded documents.'},
    {id: 'clarify', label: 'Requires clarification',
     text: 'Drafts returned for more evidence or an explanation before a decision.'},
    {id: 'approved', label: 'Approved profiles',
     text: 'Drafts that an Administrator approved. Each approval created a new profile version.'},
    {id: 'rejected', label: 'Rejected drafts',
     text: 'Drafts that an Administrator rejected. The approved profile was not changed.'}
  ];

  const CHANGE_TYPES = [
    ['Newly added', 'good'], ['Modified', 'info'], ['Removed', 'bad'],
    ['Unchanged', 'neutral'], ['Contradictory', 'warn']];

  function buildApprovalTabs() {
    const tablist = document.getElementById('approvalTablist');
    const panels = document.getElementById('approvalPanels');
    if (!tablist || !panels) return;
    CATEGORIES.forEach((cat, index) => {
      tablist.append(el('button', {type: 'button', role: 'tab', id: 'tab-' + cat.id,
                                   'aria-controls': 'panel-' + cat.id,
                                   'aria-selected': index === 0 ? 'true' : 'false', text: cat.label}));
      const tbody = el('tbody', {});
      emptyRow(tbody, 7, 'No ' + cat.label.toLowerCase(),
        'Drafts will appear here once the Data Collection Agent and approval backend are connected.');
      panels.append(el('div', {role: 'tabpanel', id: 'panel-' + cat.id, 'aria-labelledby': 'tab-' + cat.id,
                               hidden: index !== 0},
        el('p', {class: 'small muted', text: cat.text}),
        el('div', {class: 'table-host'}, el('table', {class: 'data-table'},
          el('caption', {class: 'sr-only', text: cat.label}),
          el('thead', {}, el('tr', {}, ['Organization', 'Draft type', 'Submitted', 'Source types',
                                        'Changed fields', 'Review status', 'Actions']
            .map(c => el('th', {scope: 'col', text: c})))),
          tbody))));
    });
  }

  function buildReview() {
    const summary = document.getElementById('changeSummary');
    if (!summary) return;
    summary.replaceChildren(...CHANGE_TYPES.map(([label]) => el('li', {class: 'kpi'},
      el('span', {class: 'kpi-label', text: label + ' information'}),
      el('span', {class: 'kpi-value', text: 'Not available'}))));
    document.getElementById('changeLegend').replaceChildren(...CHANGE_TYPES.map(([label, tone]) =>
      el('li', {}, badge(label, tone))));

    const compareRows = document.getElementById('compareRows');
    emptyRow(compareRows, 4, 'No draft loaded',
      'Each profile field will be shown with its current approved value, the proposed value, ' +
      'its change type and an accept / reject choice.');
    const filter = document.getElementById('compareFilter');
    filter.addEventListener('submit', e => e.preventDefault());
    document.getElementById('c-type').addEventListener('change', e => {
      emptyRow(compareRows, 4, e.target.value ? `No ${e.target.value.toLowerCase()} fields` : 'No draft loaded',
        'There is no draft to compare yet.');
    });

    emptyRow(document.getElementById('evidenceRows'), 5, 'No source evidence',
      'Source URLs, supporting quotations, publication dates and retrieval dates for each proposed ' +
      'change will appear here.');

    const notes = document.getElementById('reviewNotes');
    const count = document.getElementById('notesCount');
    const update = () => {
      count.textContent = `${notes.value.length} characters · kept in this browser tab only, not saved.`;
    };
    notes.addEventListener('input', update);
    update();
  }

  onReady(() => {
    for (const select of document.querySelectorAll('[data-source-types]')) {
      select.append(...SOURCE_TYPES.map(v => el('option', {value: v, text: v})));
    }
    buildApprovalTabs();
    buildReview();
  });
})();
