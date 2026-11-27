// Administrator module — Organizations and Organization Profile.
// No organization records are connected yet. Option lists are generic
// classification values, not data. The profile page renders the planned
// 16-section structure with empty states; documents are selected locally
// only (see AdminUI file picker) and never uploaded.
(function () {
  'use strict';
  const {el, emptyRow, onReady} = window.AdminUI;

  const CATEGORIES = ['Company', 'Investor', 'Manufacturer', 'Licensee', 'Technology co-developer',
                      'Venture capital firm', 'Research institution', 'Government agency'];
  const INDUSTRIES = ['Agriculture and food', 'Advanced materials', 'Automotive and mobility',
                      'Biotechnology', 'Chemicals', 'Construction', 'Consumer products', 'Defence and security',
                      'Electronics and semiconductors', 'Energy', 'Environment and water', 'Financial services',
                      'Healthcare and medical devices', 'Information technology', 'Manufacturing',
                      'Pharmaceuticals', 'Telecommunications', 'Transport and logistics', 'Other'];
  const REGIONS = ['Africa', 'Asia', 'Europe', 'Middle East', 'North America', 'Oceania',
                   'South and Central America', 'Global / multi-region'];
  const APPROVAL = ['Approved', 'Pending approval', 'Revision pending', 'Needs clarification',
                    'Rejected', 'No profile yet'];

  function fill(selector, values) {
    for (const select of document.querySelectorAll(selector)) {
      select.append(...values.map(v => el('option', {value: v, text: v})));
    }
  }

  // ---------------------------------------------------------- profile page
  const SECTIONS = [
    ['identity', 'Organization identity',
     ['Legal name', 'Other names', 'Category', 'Official website', 'Headquarters', 'Founded', 'Registration identifiers']],
    ['ownership', 'Ownership and leadership',
     ['Ownership structure', 'Parent organization', 'Leadership team (public roles)', 'Board']],
    ['subsidiaries', 'Subsidiaries and business units', ['Subsidiaries', 'Business units', 'Joint ventures']],
    ['portfolio', 'Current product portfolio', ['Product lines', 'Services', 'Target markets']],
    ['launches', 'Recent product launches', ['Launch', 'Date', 'Market']],
    ['strategy', 'Strategic business focus', ['Stated priorities', 'Growth areas', 'Recent strategic announcements']],
    ['manufacturing', 'Manufacturing capabilities', ['Facilities', 'Processes', 'Capacity', 'Certifications']],
    ['research', 'Technology and research capabilities', ['R&D areas', 'Research facilities', 'Academic collaborations']],
    ['financial', 'Financial capacity', ['Revenue range', 'Funding / investment history', 'Public financial reports']],
    ['patents', 'Patent and licensing history', ['Patent families', 'Licensing deals', 'Technology acquisitions']],
    ['geography', 'Geographic operations', ['Countries of operation', 'Regional offices', 'Distribution reach']],
    ['partnership', 'Potential technology partnership areas', ['Partnership areas', 'Rationale', 'Relevant inventions']],
    ['contacts', 'Public business contacts',
     ['Business development contact', 'Licensing / partnerships contact', 'General enquiries']]
  ];

  function fieldSection(index, [id, title, fields]) {
    const hid = 'sec-' + id + '-h';
    return el('section', {class: 'panel profile-section', 'aria-labelledby': hid},
      el('h2', {id: hid}, el('span', {class: 'num', text: index + '.'}), title),
      el('dl', {class: 'detail-grid'}, fields.map(f => [
        el('dt', {text: f}), el('dd', {class: 'unavailable', text: 'No information'})])),
      el('p', {class: 'small muted', style: 'margin:6px 0 0',
               text: 'Each value will show its source evidence and approval status.'}));
  }

  function tableSection(num, id, title, intro, columns, emptyTitle, emptyText) {
    const hid = 'sec-' + id + '-h';
    const tbody = el('tbody', {});
    emptyRow(tbody, columns.length, emptyTitle, emptyText);
    return el('section', {class: 'panel profile-section', 'aria-labelledby': hid},
      el('h2', {id: hid}, el('span', {class: 'num', text: num + '.'}), title),
      intro ? el('p', {class: 'small muted', text: intro}) : null,
      el('div', {class: 'table-host'}, el('table', {class: 'data-table'},
        el('caption', {class: 'sr-only', text: title}),
        el('thead', {}, el('tr', {}, columns.map(c => el('th', {scope: 'col', text: c})))),
        tbody)));
  }

  function renderProfile() {
    const host = document.getElementById('profileSections');
    if (!host) return;
    const all = SECTIONS.map((s, i) => fieldSection(i + 1, s));
    all.push(
      tableSection(14, 'gaps', 'Missing information and contradictions',
        'Gaps and conflicting statements found across sources are listed for reviewer attention.',
        ['Field', 'Issue', 'Sources involved', 'Status'],
        'Nothing to show', 'No profile has been generated, so no gaps or contradictions are recorded.'),
      tableSection(15, 'evidence', 'Source evidence', null,
        ['Source', 'URL or document', 'Supporting quotation', 'Publication date', 'Retrieval date'],
        'No source evidence', 'Evidence collected from public sources and uploaded documents will appear here.'),
      tableSection(16, 'versions', 'Profile version history', null,
        ['Version', 'Approved on', 'Approved by', 'Change summary', 'Actions'],
        'No versions', 'Approved profile versions will be listed here. Earlier versions are kept read-only.'));
    host.replaceChildren(...all);

    const toc = document.getElementById('profileToc');
    const titles = SECTIONS.map(s => [s[0], s[1]]).concat([
      ['gaps', 'Missing information and contradictions'], ['evidence', 'Source evidence'],
      ['versions', 'Profile version history']]);
    toc.replaceChildren(...titles.map(([id, title]) =>
      el('li', {}, el('a', {href: '#sec-' + id + '-h', text: title}))));
  }

  onReady(() => {
    fill('[data-org-categories]', CATEGORIES);
    fill('[data-industries]', INDUSTRIES);
    fill('[data-regions]', REGIONS);
    fill('[data-approval-statuses]', APPROVAL);

    const rows = document.getElementById('orgRows');
    if (rows) emptyRow(rows, 7, 'No organizations yet',
      'Organizations will appear here after discovery by the Data Collection Agent or manual entry, ' +
      'once the backend is connected.');
    const archived = document.getElementById('archivedRows');
    if (archived) emptyRow(archived, 5, 'No archived organizations', 'Archived organizations can be restored from here.');
    const dupes = document.getElementById('dupeRows');
    if (dupes) emptyRow(dupes, 4, 'No possible duplicates detected', 'Duplicate detection runs once organization records exist.');

    renderProfile();
  });

  window.AdminOrgOptions = {categories: CATEGORIES.slice(), industries: INDUSTRIES.slice(),
                            regions: REGIONS.slice(), approval: APPROVAL.slice()};
})();
