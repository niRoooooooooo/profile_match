// Innovation Center — Match Review (future interface, fictional data only).
// No matching is run, no score is computed, nothing is shortlisted, approved,
// rejected or sent. Sample scores come with the demo records and are shown as
// text and tables only (no graphs in this phase).
(function () {
  'use strict';
  const {el, demoLabel, futureButton, badge, formatDate, param, page, criteriaTable} = window.ICShell;
  const ICData = window.ICData;

  // Text band for a sample score (never colour alone).
  const scoreBand = score => score >= 80 ? {label: 'Strong match', tone: 'good'}
    : score >= 50 ? {label: 'Worth a look', tone: 'warn'} : {label: 'Weak match', tone: 'bad'};

  const AGENTS = [
    ['Orchestrator', 'Coordinates the agents below and hands results to staff for review.'],
    ['Data Collection Agent', 'Supplies approved company, industry, patent and investor information.'],
    ['Matching & Scoring Agent', 'Identifies relevant organisations and scores each from 0 to 100 on six criteria.'],
    ['Explanation Agent', 'Explains in plain language why an organisation matches, citing evidence.'],
    ['Risk & Compliance Agent', 'Flags competitors, conflicts of interest, confidentiality and privacy limits.'],
    ['Market Signal Agent', 'Adds funding, product-launch, hiring and other market signals.']];

  const state = {invention: null, partner: null, compare: new Set(), type: '', rankBy: 'overall'};

  function ranked(inv) {
    const rows = inv.matches.filter(m => !state.type || m.type === state.type);
    const value = m => state.rankBy === 'overall' ? m.overall : m.scores[state.rankBy];
    return rows.sort((a, b) => value(b) - value(a));
  }

  function partnerRow(m, refresh) {
    const band = scoreBand(m.overall);
    const checkId = `compare-${m.id}`;
    return el('li', {class: 'partner-row' + (state.partner === m.id ? ' selected' : '')},
      el('span', {class: 'score-pill', 'aria-label': `Sample score ${m.overall} of 100`},
        el('strong', {text: String(m.overall)}), el('span', {text: '/100'})),
      el('div', {class: 'partner-main'},
        el('button', {type: 'button', class: 'partner-open', 'aria-pressed': String(state.partner === m.id),
                      onclick: () => { state.partner = m.id; refresh(true); }},
          `${m.rank}. ${m.name}`),
        el('span', {class: 'meta', text: `${m.industry} · ${m.type}`}),
        el('span', {class: 'meta', text: `${m.location} · ${m.size} company`}),
        badge(band.label, band.tone)),
      el('label', {class: 'compare-check', for: checkId},
        el('input', {type: 'checkbox', id: checkId, checked: state.compare.has(m.id),
                     onchange: e => { e.target.checked ? state.compare.add(m.id) : state.compare.delete(m.id);
                                      refresh(false); }}), 'Compare'));
  }

  function partnerDetail(inv, m) {
    const band = scoreBand(m.overall);
    const stage = ICData.raw.engagementStages.find(s => s.id === m.engagement);
    return el('article', {class: 'panel', id: 'partner-detail', tabindex: '-1', 'aria-labelledby': 'partner-h'},
      el('div', {style: 'display:flex;gap:16px;align-items:center;flex-wrap:wrap'},
        el('span', {class: 'score-pill large', 'aria-label': `Sample score ${m.overall} of 100`},
          el('strong', {text: String(m.overall)}), el('span', {text: '/100'})),
        el('div', {},
          el('h2', {id: 'partner-h', text: m.name}),
          el('p', {}, badge('Fictional sample', 'warn'), ' ', badge(band.label, band.tone), ' ',
            badge(m.type, 'info')),
          el('p', {class: 'small muted', text:
            `Illustrative overall score ${m.overall}/100 (simple average of the six sample ` +
            'criteria). Not a production score.'}))),
      el('dl', {class: 'detail-grid'},
        ...[['Industry', m.industry], ['Partner type', m.type], ['Location', m.location],
            ['Company size', m.size], ['Engagement stage', stage ? stage.label : '—'],
            ['Strongest criterion', `${m.strongest.label} (${m.strongest.value})`]]
          .flatMap(([k, v]) => [el('dt', {text: k}), el('dd', {text: v})])),
      el('h3', {class: 'small', text: 'Six-criterion score breakdown'}),
      criteriaTable(m.scores, m.strongest.id, `Sample scores for ${m.name}`),
      el('h3', {class: 'small', text: 'Why this partner?'}),
      el('p', {text: m.why}),
      el('h3', {class: 'small', text: 'Relevant source evidence'}),
      el('ul', {class: 'compact'}, m.evidence.map(e => el('li', {}, e.text, ' ',
        el('span', {class: 'meta small', text: `— ${e.source}; confidence: ${e.confidence}`})))),
      el('h3', {class: 'small', text: 'Market-signal timeline'}),
      m.signals.length ? el('ol', {class: 'timeline'}, [...m.signals]
        .sort((a, b) => b.date.localeCompare(a.date))
        .map(s => el('li', {}, el('time', {datetime: s.date, class: 'meta', text: formatDate(s.date)}),
          el('strong', {text: s.kind}), ' — ', s.text)))
        : el('p', {class: 'doc-note', text: 'No market signals in the sample data.'}),
      el('h3', {class: 'small', text: 'Risk and conflict flags'}),
      el('ul', {class: 'alert-list'}, m.risks.map(r => el('li', {},
        badge(r.level === 'warn' ? 'Check' : 'Note', r.level === 'warn' ? 'warn' : 'neutral'), ' ', r.text))),
      el('h3', {class: 'small', text: 'Decision (future)'}),
      el('div', {class: 'outcomes'},
        futureButton('Shortlist'), futureButton('Approve for outreach'), futureButton('Reject with reason')),
      el('p', {class: 'small muted', text:
        'No partner will be contacted until Innovation Center and Industry Liaison staff approve ' +
        'the match and the outreach message.'}));
  }

  function comparison(inv) {
    const chosen = inv.matches.filter(m => state.compare.has(m.id));
    const criteria = ICData.criteria();
    const rows = [['Overall score (illustrative)', m => m.overall, true],
                  ...criteria.map(c => [c.label, m => m.scores[c.id], true]),
                  ['Partner type', m => m.type], ['Location', m => m.location],
                  ['Company size', m => m.size], ['Risk flags to check', m => m.risks.filter(r => r.level === 'warn').length]];
    return el('section', {class: 'panel', id: 'comparison', tabindex: '-1', 'aria-labelledby': 'compare-h',
                          style: 'margin-top:22px'},
      el('h2', {id: 'compare-h', text: `Side-by-side comparison (${chosen.length} partners)`}),
      el('div', {class: 'table-host'}, el('table', {class: 'compare-table'},
        el('thead', {}, el('tr', {}, el('th', {scope: 'col', text: 'Criterion'}),
          chosen.map(m => el('th', {scope: 'col', text: m.name})))),
        el('tbody', {}, rows.map(([label, get, numeric]) => {
          const values = chosen.map(get);
          const best = numeric ? Math.max(...values) : null;
          return el('tr', {}, el('th', {scope: 'row', text: label}),
            values.map(v => el('td', {class: numeric && v === best ? 'best' : null},
              String(v), numeric && v === best ? el('span', {class: 'sr-only', text: ' (highest)'}) : null)));
        })))));
  }

  page(main => {
    const candidates = ICData.inventions().filter(i => i.stageIndex >= 4);   // verified or later
    const requested = param('invention');
    state.invention = (candidates.find(i => i.id === requested) || candidates.find(i => i.matched)
                       || candidates[0]).id;

    main.append(
      el('h1', {text: 'Match review'}),
      el('p', {class: 'lead', text:
        'Where Innovation Center and Industry Liaison staff will review partner recommendations ' +
        'together before anyone is contacted.'}),
      el('div', {class: 'preview-callout', role: 'note'}, el('strong', {text: 'No matching has been run. '}),
        'Companies, scores, evidence and signals below are fictional examples showing how future ' +
        'recommendations will be presented.'),
      demoLabel(),
      el('details', {class: 'panel', style: 'margin:12px 0'},
        el('summary', {text: 'How future recommendations will be produced'}),
        el('dl', {class: 'agents', style: 'margin-top:10px'},
          AGENTS.map(([name, role]) => el('div', {}, el('dt', {text: name}), el('dd', {text: role}))))));

    const controls = el('form', {class: 'filters', 'aria-label': 'Choose invention and ranking',
                                 onsubmit: e => e.preventDefault()});
    const body = el('div', {});
    main.append(controls, body);

    const typeSelect = el('select', {id: 'partner-type', onchange: e => { state.type = e.target.value; refresh(false); }});
    const rankSelect = el('select', {id: 'rank-by', onchange: e => { state.rankBy = e.target.value; refresh(false); }},
      el('option', {value: 'overall', text: 'Overall score'}),
      ICData.criteria().map(c => el('option', {value: c.id, text: c.label})));
    controls.append(
      el('label', {class: 'filter grow', for: 'invention-select'}, 'Invention',
        el('select', {id: 'invention-select', onchange: e => {
          state.invention = e.target.value; state.partner = null; state.compare.clear(); state.type = '';
          history.replaceState(null, '', `match-review.html?invention=${state.invention}`);
          refresh(false);
        }}, candidates.map(i => el('option', {value: i.id, selected: i.id === state.invention,
          text: `${i.title} — ${i.matched ? `${i.matches.length} sample partners` : 'Not matched yet'}`})))),
      el('label', {class: 'filter', for: 'partner-type'}, 'Partner type', typeSelect),
      el('label', {class: 'filter', for: 'rank-by'}, 'Rank by', rankSelect));

    function refresh(focusDetail) {
      const inv = ICData.invention(state.invention);
      const types = [...new Set(inv.matches.map(m => m.type))].sort();
      typeSelect.replaceChildren(el('option', {value: '', text: 'All'}),
        types.map(t => el('option', {value: t, text: t, selected: t === state.type})));
      typeSelect.disabled = !inv.matched;
      rankSelect.disabled = !inv.matched;
      if (!inv.matched) {
        body.replaceChildren(el('section', {class: 'panel'},
          el('h2', {text: 'Not matched yet'}),
          el('p', {text: `${inv.title} is ${inv.stageLabel.toLowerCase()}. Partner matching has not ` +
                         'been run, so there are no candidates to review.'}),
          futureButton('Run partner matching', 'The Matching & Scoring Agent is a future phase.')));
        return;
      }
      const list = ranked(inv);
      if (!list.some(m => m.id === state.partner)) state.partner = list.length ? list[0].id : null;
      const selected = inv.matches.find(m => m.id === state.partner);
      const compareCount = state.compare.size;
      body.replaceChildren(...[
        el('p', {class: 'result-count', 'aria-live': 'polite',
                 text: `${list.length} fictional candidate partners for ${inv.title}`}),
        el('div', {class: 'match-layout'},
          el('section', {'aria-labelledby': 'ranked-h'},
            el('h2', {id: 'ranked-h', class: 'panel-title', text: 'Ranked partners'}),
            el('ol', {class: 'partner-list'}, list.map(m => partnerRow(m, refresh))),
            el('button', {type: 'button', class: 'btn', disabled: compareCount < 2,
                          'aria-describedby': 'compare-help',
                          onclick: () => { const c = document.getElementById('comparison');
                                           if (c) { c.scrollIntoView({block: 'start'}); c.focus({preventScroll: true}); } }},
              `Compare selected (${compareCount})`),
            el('p', {id: 'compare-help', class: 'small muted', text: 'Tick two or more partners to compare them.'})),
          selected ? partnerDetail(inv, selected) : el('p', {class: 'doc-note', text: 'No partner of this type.'})),
        compareCount >= 2 ? comparison(inv) : null].filter(Boolean));
      if (focusDetail) {
        const detail = document.getElementById('partner-detail');
        if (detail) { detail.scrollIntoView({block: 'nearest'}); detail.focus({preventScroll: true}); }
      }
    }
    refresh(false);
  });
})();
