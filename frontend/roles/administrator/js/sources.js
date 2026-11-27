// Administrator module — Data Sources.
// Source categories are planned classifications, not registered sources. No
// source is stored, enabled or contacted.
(function () {
  'use strict';
  const {el, emptyRow, onReady} = window.AdminUI;

  const CATEGORIES = [
    ['Official company websites', 'Company pages, product catalogues and press rooms.'],
    ['Government databases', 'Company registries, procurement and grant records.'],
    ['Patent databases', 'Patent filings, grants and assignments.'],
    ['Industry directories', 'Sector associations and supplier directories.'],
    ['Investor websites', 'Portfolio pages of investors and venture capital firms.'],
    ['Financial reports', 'Annual reports and regulatory filings.'],
    ['News publications', 'Business and trade press.'],
    ['Public APIs', 'Open data services with published terms of use.'],
    ['Employee-uploaded documents', 'PDF, DOC and DOCX files added by staff.']
  ];

  onReady(() => {
    const grid = document.getElementById('sourceCategories');
    grid.replaceChildren(...CATEGORIES.map(([name, text]) => el('li', {class: 'kpi'},
      el('strong', {text: name, style: 'font-size:15px'}),
      el('span', {class: 'kpi-label', text}),
      el('span', {class: 'kpi-value', text: 'No sources registered'}))));

    for (const select of document.querySelectorAll('[data-source-categories]')) {
      select.append(...CATEGORIES.map(([name]) => el('option', {value: name, text: name})));
    }

    emptyRow(document.getElementById('sourceRows'), 10, 'No data sources registered',
      'Sources will be listed here once the source registry is connected. Enable, disable, edit and ' +
      'remove actions will be available on each row.');
  });
})();
