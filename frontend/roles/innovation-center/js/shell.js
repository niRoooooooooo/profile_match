// Innovation Center page helpers (shared by the four pages).
// Pages are real HTML files, so a browser refresh keeps the current page and
// its query (e.g. profile-approvals.html?review=rl3).
(function () {
  'use strict';

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(typeof child === 'string' || typeof child === 'number' ? String(child) : child);
    }
    return node;
  }

  // Access computed by the SERVER for this page (data-interface-* on <body>).
  // It only hides what the server refuses anyway; it never grants anything.
  // Opened from disk (offline UI tests) there is no server, so the full
  // fictional preview is shown. Served over HTTP without the attributes:
  // nothing is allowed (fail closed).
  const OFFLINE = location.protocol === 'file:';
  const words = name => new Set((document.body.dataset[name] || '').split(' ').filter(Boolean));
  const can = permission => OFFLINE || words('interfacePermissions').has(permission);
  const canOpen = pageFile => OFFLINE || words('interfacePages').has(pageFile);
  const PAGE_FILES = ['overview.html', 'profile-approvals.html', 'portfolio.html', 'match-review.html'];

  // Links to pages this account may not open: navigation entries are removed,
  // links inside content become plain text.
  function applyPageAccess(root) {
    for (const link of root.querySelectorAll('a[href]')) {
      const file = (link.getAttribute('href') || '').split(/[?#]/)[0];
      if (!PAGE_FILES.includes(file) || canOpen(file)) continue;
      if (link.closest('.ic-nav, .quick-links')) link.remove();
      else link.replaceWith(el('span', {text: link.textContent}));
    }
    for (const nav of root.querySelectorAll('.quick-links')) {
      if (!nav.querySelector('a')) nav.remove();
    }
  }

  function demoLabel(extra) {
    return el('p', {class: 'demo-label'},
      el('span', {class: 'demo-tag', text: 'Illustrative demo data'}),
      extra ? ' ' + extra : null);
  }

  // Visible-but-disabled control for functionality that does not exist yet.
  // With `permission`, it is not shown at all to accounts without it (for
  // example Head-only decisions for Employees).
  let futureCount = 0;
  function futureButton(label, explanation, permission) {
    if (permission && !can(permission)) return null;
    const id = 'future-note-' + (++futureCount);
    return el('span', {class: 'future-control'},
      el('button', {type: 'button', class: 'btn', disabled: true,
                    'aria-disabled': 'true', 'aria-describedby': id, text: label}),
      el('span', {id, class: 'future-note',
                  text: explanation || 'Available after staff access is implemented.'}));
  }

  const badge = (text, tone) => el('span', {class: 'badge tone-' + (tone || 'neutral'), text});

  function formatDate(iso) {
    if (!iso) return '—';
    const date = new Date(iso.length === 10 ? iso + 'T00:00:00Z' : iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric',
                                              timeZone: 'UTC'});
  }

  const trl = value => (value ? `TRL ${value}` : '—');
  const param = name => new URLSearchParams(location.search).get(name);

  // Render a page into <main>; the sidebar link for data-page is marked current.
  function page(render) {
    document.addEventListener('DOMContentLoaded', () => {
      const current = document.body.dataset.page;
      for (const link of document.querySelectorAll('.ic-nav a[data-page]')) {
        if (link.dataset.page === current) link.setAttribute('aria-current', 'page');
      }
      const main = document.getElementById('main');
      main.replaceChildren();
      render(main);
      applyPageAccess(document);
      const heading = main.querySelector('h1');
      if (heading) {
        heading.setAttribute('tabindex', '-1');
        document.title = `${heading.textContent} · Innovation Center | Profile Match`;
      }
    });
  }

  // Six-criterion scores as a plain table (no graphs in this phase).
  function criteriaTable(scores, strongestId, caption) {
    return el('table', {class: 'criteria-table'},
      el('caption', {class: 'sr-only', text: caption || 'Six-criterion scores'}),
      el('thead', {}, el('tr', {}, el('th', {scope: 'col', text: 'Criterion'}),
                                   el('th', {scope: 'col', text: 'Score (0-100)'}))),
      el('tbody', {}, window.ICData.criteria().map(c => {
        const best = c.id === strongestId;
        return el('tr', {class: best ? 'strongest' : null},
          el('th', {scope: 'row'}, c.label, best ? ' ' : null,
             best ? el('span', {class: 'badge tone-good', text: 'Strongest'}) : null),
          el('td', {text: String(scores[c.id])}));
      })));
  }

  // Reserved space for analytics that will use real data later. The buttons
  // are disabled on purpose: no analytics, data fetching or calculations yet.
  const TRENDS = [
    {id: 'pipeline', title: 'Pipeline Trends & Reports', button: 'View Pipeline Trends & Reports',
     text: 'How inventions move through the technology-transfer pipeline over time.',
     items: ['Commercialization progress by stage', 'Partner engagement stages',
             'Licensing trends', 'Pipeline statistics']},
    {id: 'domain', title: 'Technology Domain Trends & Reports',
     button: 'View Technology Domain Trends & Reports',
     text: 'How the portfolio is distributed and developing across technology domains.',
     items: ['Invention distribution by technology domain', 'Domain growth over time',
             'Readiness (TRL) levels', 'Matching opportunities by domain']}];

  function trendsPlaceholders() {
    if (!can('innovation_center.reports.view')) return null;
    return el('section', {class: 'trends', 'aria-labelledby': 'trends-h'},
      el('h2', {id: 'trends-h', class: 'section-title', text: 'Trends & reports'}),
      el('div', {class: 'trends-grid'}, TRENDS.map(t => el('article', {
        class: 'placeholder', 'aria-labelledby': `trends-${t.id}-h`},
        el('h3', {id: `trends-${t.id}-h`, text: t.title}),
        el('p', {text: t.text + ' Charts and reports will appear here once real database and ' +
                         'agent-generated information is connected.'}),
        el('p', {class: 'small muted', text: 'Will include:'}),
        el('ul', {class: 'compact'}, t.items.map(i => el('li', {text: i}))),
        el('button', {type: 'button', class: 'btn', disabled: true, 'aria-disabled': 'true',
                      'aria-describedby': `trends-${t.id}-note`, 'data-trends': t.id, text: t.button}),
        el('p', {id: `trends-${t.id}-note`, class: 'coming-soon-note',
                 text: 'Coming Soon — Available After Data Integration'})))));
  }

  // An empty state for information that is not available yet.
  function notAvailable(label) {
    return el('li', {class: 'kpi placeholder-kpi'},
      el('span', {class: 'kpi-label', text: label}),
      el('span', {class: 'kpi-empty', text: 'Not available yet'}));
  }

  window.ICShell = {el, demoLabel, futureButton, badge, formatDate, trl, param, page,
                    criteriaTable, trendsPlaceholders, notAvailable, can, canOpen};
})();
