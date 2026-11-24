// Innovation Center — Portfolio and commercialization readiness.
// Fictional sample records via ICData. Match information appears ONLY for
// inventions with illustrative sample matches; every other invention shows
// "Not matched yet". No charts or analytics in this phase: trends and reports
// are placeholders until real data is connected.
(function () {
  'use strict';
  const {el, demoLabel, badge, formatDate, trl, param, page, criteriaTable,
         trendsPlaceholders} = window.ICShell;
  const ICData = window.ICData;
  const NOT_MATCHED = 'Not matched yet';

  const state = {search: '', stage: '', domain: ''};

  function stepper(inv) {
    const stages = ICData.stages();
    const list = el('ol', {class: 'stepper', 'aria-label': `Lifecycle of ${inv.title}`});
    stages.forEach((stage, i) => {
      let cls = i < inv.stageIndex ? 'done' : i === inv.stageIndex ? 'current' : '';
      let text = stage.label;
      if (i === inv.stageIndex && inv.reviewStatus === 'clarification') {
        cls = 'blocked'; text += ' — needs clarification';
      } else if (i === inv.stageIndex && inv.reviewStatus === 'on_hold') {
        cls = 'stopped'; text += ' — rejected / on hold';
      }
      const state = cls === 'done' ? 'completed' : i === inv.stageIndex ? 'current stage' : 'not reached';
      list.append(el('li', {class: cls || null, 'aria-current': i === inv.stageIndex ? 'step' : null},
        text, el('span', {class: 'sr-only', text: ` (${state})`})));
    });
    return list;
  }

  function matchSummary(inv) {
    if (!inv.matched) {
      return el('p', {class: 'not-matched', text: inv.stageIndex >= 4
        ? `${NOT_MATCHED}. Partner matching has not been run for this invention.`
        : `${NOT_MATCHED}. Matching starts only after institutional verification.`});
    }
    const top = inv.top;
    return el('div', {},
      el('p', {}, el('strong', {text: top.name}), ' ', badge('Fictional sample', 'warn'),
        ` — overall ${top.overall}/100 · strongest criterion: ${top.strongest.label} (${top.strongest.value})`),
      criteriaTable(top.scores, top.strongest.id, `Sample scores for ${top.name}`),
      el('p', {class: 'small muted', text:
        'Illustrative overall score = simple average of the six sample criteria. Real scores will ' +
        'come from the future Matching & Scoring Agent.'}),
      el('a', {class: 'btn small', href: `match-review.html?invention=${inv.id}`,
               text: `Open in Match review (${inv.matches.length} sample partners)`}));
  }

  function detail(inv) {
    return el('section', {class: 'panel', id: 'portfolio-detail', tabindex: '-1',
                          'aria-labelledby': 'detail-h', style: 'margin-top:18px'},
      el('h2', {id: 'detail-h', text: inv.title}),
      el('p', {}, badge(inv.status.label, inv.status.tone), ' ', badge(inv.stageLabel, 'info')),
      el('h3', {class: 'small', text: 'Commercialization lifecycle'}),
      stepper(inv),
      el('p', {class: 'side-paths', text:
        'Other paths: Needs clarification returns the report to the innovator, then back to ' +
        'review. Rejected / on hold stops progress until the reviewer reopens it.'}),
      el('dl', {class: 'detail-grid'},
        ...[['Innovator', inv.inventor], ['Technical domain', inv.domain],
            ['Registered', formatDate(inv.registered)],
            ['Declared TRL', trl(inv.declaredTrl)], ['AI-estimated TRL', trl(inv.aiTrl)],
            ['Staff-assessed TRL', inv.assessedTrl ? trl(inv.assessedTrl) : 'Not assessed yet'],
            ['Latest activity', `${formatDate(inv.latest.date)} — ${inv.latest.text}`],
            ['Next recommended action', inv.next]]
          .flatMap(([k, v]) => [el('dt', {text: k}), el('dd', {text: v})])),
      el('h3', {class: 'small', text: 'Partner matching'}),
      matchSummary(inv));
  }

  function table(rows, onOpen) {
    const headers = ['Invention', 'Innovator', 'Technical domain', 'Registered', 'Declared TRL',
                     'AI-estimated TRL', 'Staff-assessed TRL', 'Verification status',
                     'Commercialization stage', 'Potential partners', 'Highest-scoring partner',
                     'Highest match score', 'Strongest criterion', 'Latest activity',
                     'Next recommended action'];
    return el('table', {class: 'queue-table portfolio-table'},
      el('caption', {class: 'sr-only', text: 'Invention portfolio (illustrative)'}),
      el('thead', {}, el('tr', {}, headers.map(h => el('th', {scope: 'col', text: h})))),
      el('tbody', {}, rows.length ? rows.map(inv => el('tr', {},
        el('th', {scope: 'row', 'data-label': 'Invention'},
          el('button', {type: 'button', class: 'link-button', text: inv.title,
                        'aria-label': `Show progress of ${inv.title}`, onclick: () => onOpen(inv.id)})),
        el('td', {'data-label': 'Innovator', text: inv.inventor}),
        el('td', {'data-label': 'Technical domain', text: inv.domain}),
        el('td', {'data-label': 'Registered'}, el('time', {datetime: inv.registered, text: formatDate(inv.registered)})),
        el('td', {'data-label': 'Declared TRL', text: trl(inv.declaredTrl)}),
        el('td', {'data-label': 'AI-estimated TRL', text: inv.aiTrl ? trl(inv.aiTrl) : 'Not estimated'}),
        el('td', {'data-label': 'Staff-assessed TRL', text: inv.assessedTrl ? trl(inv.assessedTrl) : 'Not assessed'}),
        el('td', {'data-label': 'Verification status'}, badge(inv.status.label, inv.status.tone)),
        el('td', {'data-label': 'Commercialization stage', text: inv.stageLabel}),
        el('td', {'data-label': 'Potential partners', class: inv.matched ? null : 'not-matched',
                  text: inv.matched ? String(inv.matches.length) : NOT_MATCHED}),
        el('td', {'data-label': 'Highest-scoring partner', text: inv.matched ? `${inv.top.name} (fictional)` : '—'}),
        el('td', {'data-label': 'Highest match score', class: inv.matched ? 'score-inline' : null,
                  text: inv.matched ? `${inv.top.overall}/100` : '—'}),
        el('td', {'data-label': 'Strongest criterion',
                  text: inv.matched ? `${inv.top.strongest.label} (${inv.top.strongest.value})` : '—'}),
        el('td', {'data-label': 'Latest activity'}, el('span', {class: 'meta', text: formatDate(inv.latest.date)}),
          el('br'), inv.latest.text),
        el('td', {'data-label': 'Next recommended action', text: inv.next})))
        : [el('tr', {}, el('td', {colspan: headers.length, class: 'empty',
                                  text: 'No inventions match these filters.'}))]));
  }

  page(main => {
    const all = ICData.inventions();
    main.append(
      el('div', {class: 'page-head'},
        el('div', {}, el('h1', {text: 'Portfolio and commercialization readiness'}),
          el('p', {class: 'lead', text:
            'Every invention across the technology-transfer lifecycle: readiness, verification, ' +
            'matching and engagement, with the next action needed.'})),
        el('nav', {class: 'quick-links', 'aria-label': 'Quick navigation'},
          el('a', {class: 'btn small', href: 'profile-approvals.html', text: 'Profile approvals'}),
          el('a', {class: 'btn small', href: 'match-review.html', text: 'Match review'}))),
      demoLabel('Fictional inventions, companies and scores. No partner matching has been run.'));

    const stages = ICData.stages();
    const domains = [...new Set(all.map(i => i.domain))].sort();
    const result = el('p', {class: 'result-count', 'aria-live': 'polite'});
    const host = el('div', {class: 'table-host'});
    const detailHost = el('div', {});
    const open = id => {
      const inv = ICData.invention(id);
      detailHost.replaceChildren(detail(inv));
      history.replaceState(null, '', `portfolio.html?id=${encodeURIComponent(id)}`);
      const panel = document.getElementById('portfolio-detail');
      panel.scrollIntoView({block: 'start'});
      panel.focus({preventScroll: true});
    };
    const refresh = () => {
      const term = state.search.trim().toLowerCase();
      const rows = all.filter(i => (!term || `${i.title} ${i.inventor} ${i.domain}`.toLowerCase().includes(term))
        && (!state.stage || i.stage === state.stage) && (!state.domain || i.domain === state.domain));
      result.textContent = `${rows.length} of ${all.length} inventions shown`;
      host.replaceChildren(table(rows, open));
    };
    const select = (id, label, options, key) => el('label', {class: 'filter', for: id}, label,
      el('select', {id, onchange: e => { state[key] = e.target.value; refresh(); }},
        el('option', {value: '', text: 'All'}), options.map(([v, t]) => el('option', {value: v, text: t}))));

    main.append(
      el('form', {class: 'filters', role: 'search', 'aria-label': 'Filter portfolio',
                  onsubmit: e => e.preventDefault()},
        el('label', {class: 'filter grow', for: 'portfolio-search'}, 'Search',
          el('input', {id: 'portfolio-search', type: 'search', placeholder: 'Title, innovator or domain',
                       oninput: e => { state.search = e.target.value; refresh(); }})),
        select('portfolio-stage', 'Commercialization stage', stages.map(s => [s.id, s.label]), 'stage'),
        select('portfolio-domain', 'Technical domain', domains.map(d => [d, d]), 'domain')),
      result, host, detailHost);
    refresh();
    const initial = param('id');
    if (initial && ICData.invention(initial)) detailHost.replaceChildren(detail(ICData.invention(initial)));

    main.append(trendsPlaceholders());
  });
})();
