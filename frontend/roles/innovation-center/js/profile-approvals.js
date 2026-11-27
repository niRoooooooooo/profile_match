// Innovation Center — Profile Approvals: review queue and review workspace.
// Fictional demo data via ICData. Reviewer choices live only in memory on
// this screen; nothing is saved, sent, approved or rejected.
(function () {
  'use strict';
  const {el, demoLabel, futureButton, badge, formatDate, param, page} = window.ICShell;
  const ICData = window.ICData;

  const STATUS_TONE = {verified: 'good', interpretation: 'info', recommendation: 'info',
                       declared: 'neutral', edited: 'info', unverified: 'warn',
                       discrepancy: 'warn', contradiction: 'warn'};

  // ---------------------------------------------------------------- queue

  const queueState = {search: '', status: '', domain: '', confidentiality: '',
                      sort: 'submitted', direction: 'desc'};

  const COLUMNS = [
    ['title', 'Invention'], ['inventor', 'Inventor'], ['domain', 'Technical domain'],
    ['declaredTrl', 'Declared TRL'], ['aiTrl', 'AI-estimated TRL'],
    ['confidentiality', 'Confidentiality'], ['submitted', 'Submitted'],
    ['status', 'Verification status']];

  function filteredQueue(queue) {
    const term = queueState.search.trim().toLowerCase();
    const rows = queue.filter(item =>
      (!term || [item.title, item.inventor, item.domain].join(' ').toLowerCase().includes(term))
      && (!queueState.status || item.reviewStatus === queueState.status)
      && (!queueState.domain || item.domain === queueState.domain)
      && (!queueState.confidentiality || item.confidentiality === queueState.confidentiality));
    const key = queueState.sort;
    const factor = queueState.direction === 'asc' ? 1 : -1;
    return rows.sort((a, b) => {
      const x = key === 'status' ? a.status.label : (a[key] ?? -1);
      const y = key === 'status' ? b.status.label : (b[key] ?? -1);
      return (typeof x === 'number' && typeof y === 'number'
        ? x - y : String(x).localeCompare(String(y))) * factor;
    });
  }

  function select(id, label, value, options, onChange) {
    return el('label', {class: 'filter', for: id}, label,
      el('select', {id, onchange: e => onChange(e.target.value)},
        el('option', {value: '', text: 'All'}),
        options.map(([v, text]) => el('option', {value: v, text, selected: v === value}))));
  }

  function renderQueue(main) {
    const queue = ICData.reviewQueue();
    const statuses = ICData.statuses();
    delete statuses.not_submitted;          // the queue lists submitted reports only
    main.append(
      el('h1', {text: 'Profile approvals'}),
      el('p', {class: 'lead', text:
        'Inventors submit AI-generated invention reports here. Staff check each report against ' +
        'the original documents before it can be used for partner matching. An innovator ' +
        'submission is never an institutional approval.'}),
      demoLabel('Records, names and dates are fictional samples.'),
      el('p', {class: 'small muted', text:
        'Staff compare three things: the AI-generated report, the original innovator documents ' +
        'and the registration details. Open a submission to review it.'}));

    const counts = el('ul', {class: 'status-summary', 'aria-label': 'Records by review status'},
      Object.entries(statuses).map(([key, s]) => el('li', {},
        badge(s.label, s.tone), ' ',
        el('strong', {text: String(queue.filter(q => q.reviewStatus === key).length)}))));
    main.append(counts);

    const domains = [...new Set(queue.map(q => q.domain))].sort().map(d => [d, d]);
    const levels = [...new Set(queue.map(q => q.confidentiality))].sort().map(c => [c, c]);
    const result = el('p', {class: 'result-count', 'aria-live': 'polite'});
    const tableHost = el('div', {class: 'table-host'});

    const refresh = () => {
      const rows = filteredQueue(queue);
      result.textContent = `${rows.length} of ${queue.length} submissions shown`;
      tableHost.replaceChildren(queueTable(rows, statuses, refresh));
    };
    const set = key => value => { queueState[key] = value; refresh(); };

    const search = el('input', {id: 'queue-search', type: 'search', value: queueState.search,
                                placeholder: 'Title, inventor or domain',
                                oninput: e => set('search')(e.target.value)});
    main.append(el('form', {class: 'filters', role: 'search', 'aria-label': 'Filter submissions',
                            onsubmit: e => e.preventDefault()},
      el('label', {class: 'filter grow', for: 'queue-search'}, 'Search', search),
      select('queue-status', 'Review status', queueState.status,
             Object.entries(statuses).map(([k, s]) => [k, s.label]), set('status')),
      select('queue-domain', 'Domain', queueState.domain, domains, set('domain')),
      select('queue-conf', 'Confidentiality', queueState.confidentiality, levels,
             set('confidentiality')),
      el('button', {type: 'button', class: 'btn', text: 'Clear filters', onclick: () => {
        Object.assign(queueState, {search: '', status: '', domain: '', confidentiality: ''});
        main.replaceChildren();
        renderQueue(main);
        document.getElementById('queue-search').focus();
      }})),
      result, tableHost);
    refresh();
  }

  function queueTable(rows, statuses, refresh) {
    const head = el('tr', {}, COLUMNS.map(([key, label]) => {
      const active = queueState.sort === key;
      return el('th', {scope: 'col', 'aria-sort': active
          ? (queueState.direction === 'asc' ? 'ascending' : 'descending') : 'none'},
        el('button', {type: 'button', class: 'sort', onclick: () => {
          queueState.direction = active && queueState.direction === 'asc' ? 'desc' : 'asc';
          queueState.sort = key; refresh();
        }}, label, el('span', {class: 'sort-mark', 'aria-hidden': 'true',
                              text: active ? (queueState.direction === 'asc' ? ' ▲' : ' ▼') : ''})));
    }), el('th', {scope: 'col', text: 'Review action'}));

    const body = rows.map(item => {
      const status = item.status;
      return el('tr', {},
        el('th', {scope: 'row', 'data-label': 'Invention'}, item.title),
        el('td', {'data-label': 'Inventor', text: item.inventor}),
        el('td', {'data-label': 'Technical domain', text: item.domain}),
        el('td', {'data-label': 'Declared TRL', text: item.declaredTrl ? `TRL ${item.declaredTrl}` : '—'}),
        el('td', {'data-label': 'AI-estimated TRL', text: item.aiTrl ? `TRL ${item.aiTrl}` : 'Not estimated'}),
        el('td', {'data-label': 'Confidentiality', text: item.confidentiality}),
        el('td', {'data-label': 'Submitted'}, el('time', {datetime: item.submitted,
                                                         text: formatDate(item.submitted)})),
        el('td', {'data-label': 'Verification status'}, badge(status.label, status.tone)),
        el('td', {'data-label': 'Review action'},
          el('a', {class: 'btn small', href: `profile-approvals.html?review=${item.id}`,
                   'aria-label': `Review ${item.title}`, text: 'Review'})));
    });
    if (!rows.length) {
      body.push(el('tr', {}, el('td', {colspan: COLUMNS.length + 1, class: 'empty',
                                       text: 'No submissions match these filters.'})));
    }
    return el('table', {class: 'queue-table'},
      el('caption', {class: 'sr-only', text: 'Submitted invention profiles (illustrative)'}),
      el('thead', {}, head), el('tbody', {}, body));
  }

  // ------------------------------------------------------------ workspace

  function sourceIndex(report) {
    const key = (file, page, section) => [file, page ?? '', section || ''].join('|');
    const map = new Map(report.sources.map(s => [key(s.source_file, s.page, s.section), s.number]));
    return evidence => (evidence || [])
      .map(ev => map.get(key(ev.source_file, ev.page, ev.section)))
      .filter(Boolean);
  }

  function citeButtons(numbers, ws) {
    return [...new Set(numbers)].sort((a, b) => a - b).map(n => {
      const src = ws.report.sources[n - 1];
      const where = src ? `${src.source_file}${src.page != null ? ', page ' + src.page : ''}` +
        `${src.section ? ', section ' + src.section : ''}` : '';
      return el('button', {type: 'button', class: 'cite', text: `[${n}]`,
                           'aria-label': `Show source ${n}: ${where}`,
                           onclick: () => ws.showSource(n)});
    });
  }

  function itemLabel(item) {
    if (!item.label) return null;
    const text = item.status === 'unverified' ? '⚠ Unverified' : item.label;
    return badge(text, STATUS_TONE[item.status]);
  }

  function renderReport(ws) {
    const r = ws.report;
    const panel = el('article', {class: 'report-view', 'aria-labelledby': 'report-heading'});
    panel.append(
      el('h2', {id: 'report-heading', class: 'panel-title', text: 'AI-generated invention report'}),
      el('p', {class: 'report-title', text: r.title}),
      el('p', {class: 'report-meta'}, badge(r.notice, 'warn')),
      r.version ? el('p', {class: 'report-meta', text: r.version}) : null,
      el('p', {class: 'report-meta', text: r.metadata.map(m => `${m.name}: ${m.value}`).join(' · ')}),
      el('p', {class: 'report-disclaimer', text: r.disclaimer}),
      el('p', {class: 'report-legend', text: r.legend}));

    for (const section of r.sections) {
      const s = el('section', {id: `sec-${section.number}`, class: 'report-section',
                               'aria-labelledby': `sec-h-${section.number}`, tabindex: '-1'},
        el('h3', {id: `sec-h-${section.number}`, text: `${section.number}. ${section.title}`}));
      for (const block of section.blocks) {
        if (block.kind === 'note') { s.append(el('p', {class: 'doc-note', text: block.text})); continue; }
        if (block.heading && block.kind !== 'facts') {
          s.append(el('h4', {}, block.heading,
            block.label ? el('span', {class: 'block-label', text: block.label}) : null));
        } else if (block.label && (block.kind === 'facts' || block.kind === 'bullets')) {
          s.append(el('p', {class: 'block-label', text: block.label}));
        }
        if (block.kind === 'paragraph') {
          for (const item of block.items) {
            const parts = item.text.split(/\n+/).filter(t => t.trim());
            parts.forEach((part, i) => s.append(el('p', {}, part.trim(),
              i === parts.length - 1 ? [...citeButtons(item.citations, ws), itemLabel(item),
                !block.heading && block.label ? badge(block.label, STATUS_TONE[block.status]) : null] : null)));
          }
        } else if (block.kind === 'facts') {
          s.append(el('dl', {class: 'facts'}, block.items.map(item => [
            el('dt', {text: item.name || ''}),
            el('dd', {}, item.text, citeButtons(item.citations, ws), itemLabel(item))])));
        } else if (block.kind === 'bullets') {
          s.append(el('ul', {}, block.items.map(item =>
            el('li', {}, item.text, citeButtons(item.citations, ws), itemLabel(item)))));
        } else if (block.kind === 'table') {
          const showStatus = block.items.some(i => i.label);
          s.append(el('table', {class: 'results-table'},
            el('thead', {}, el('tr', {}, ['Result', 'Source', showStatus ? 'Status' : null]
              .filter(Boolean).map(h => el('th', {scope: 'col', text: h})))),
            el('tbody', {}, block.items.map(item => el('tr', {},
              el('td', {text: item.text}),
              el('td', {}, item.citations.length ? citeButtons(item.citations, ws) : '—'),
              showStatus ? el('td', {}, itemLabel(item) || 'Documented') : null)))));
        }
      }
      if (section.key === 'sources' && r.sources.length) {
        s.append(el('h4', {text: 'References'}), el('ol', {class: 'references'},
          r.sources.map(src => el('li', {value: src.number},
            el('button', {type: 'button', class: 'link-button',
                          onclick: () => ws.showSource(src.number)},
              `${src.source_file}${src.page != null ? ' (page ' + src.page + ')' : ''}` +
              `${src.section ? ' (section ' + src.section + ')' : ''}`),
            src.excerpts.map(x => el('blockquote', {text: `“${x}”`})),
            !src.excerpts.length && src.note ? el('p', {class: 'doc-note', text: src.note}) : null))));
      }
      panel.append(s);
    }
    return panel;
  }

  // Highlight every excerpt inside a chunk of extracted document text.
  function highlighted(text, excerpts) {
    const ranges = [];
    for (const excerpt of excerpts) {
      const words = excerpt.trim().split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      if (!words.length) continue;
      const match = new RegExp(words.join('[\\s\\-]+'), 'i').exec(text);
      if (match) ranges.push([match.index, match.index + match[0].length]);
    }
    ranges.sort((a, b) => a[0] - b[0]);
    const nodes = [];
    let position = 0;
    for (const [start, end] of ranges) {
      if (start < position) continue;
      if (start > position) nodes.push(text.slice(position, start));
      nodes.push(el('mark', {text: text.slice(start, end)}));
      position = end;
    }
    nodes.push(text.slice(position));
    return {nodes, found: ranges.length};
  }

  function chunkMatches(chunk, src) {
    if (src.page != null) return chunk.page === src.page;
    if (src.section) return chunk.section === src.section;
    return true;
  }

  function relevanceBadge(relevance) {
    return badge(relevance === 'relevant' ? 'Analysed' : `Excluded (${relevance})`,
                 relevance === 'relevant' ? 'good' : 'neutral');
  }

  function renderEvidenceViewer(ws, host) {
    host.replaceChildren();
    const sel = ws.selection;
    const docs = ws.sample.documents;
    if (!sel) {
      host.append(el('p', {class: 'muted', text:
        'Select a citation such as [1] in the report, or a document below, to see the ' +
        'supporting passage in the extracted document text.'}));
      return;
    }
    const doc = docs.find(d => d.filename === (sel.source ? sel.source.source_file : sel.file));
    const sources = sel.source ? [sel.source]
      : ws.report.sources.filter(s => s.source_file === sel.file);
    const title = sel.source
      ? `Source [${sel.source.number}]: ${sel.source.source_file}` : `Document: ${sel.file}`;
    host.append(el('h4', {text: title}));
    if (doc) host.append(el('p', {class: 'report-meta'}, relevanceBadge(doc.relevance)));
    if (!doc) {
      host.append(el('p', {class: 'doc-note', text: 'The document text is not included in this sample.'}));
      return;
    }
    const chunks = doc.chunks.filter(c => !sel.source || chunkMatches(c, sel.source));
    let found = 0;
    for (const chunk of chunks) {
      const excerpts = sources.filter(s => chunkMatches(chunk, s)).flatMap(s => s.excerpts);
      const {nodes, found: n} = highlighted(chunk.text, excerpts);
      found += n;
      const where = [chunk.page != null ? `Page ${chunk.page}` : null,
                     chunk.section ? `Section: ${chunk.section}` : null].filter(Boolean).join(' · ');
      host.append(el('figure', {class: 'evidence-chunk'},
        el('figcaption', {text: where || 'Document text'}), el('pre', {}, nodes)));
    }
    if (sel.source && !found) {
      host.append(el('p', {class: 'doc-note', text:
        'The quoted passage could not be located in the extracted text; check the original file.'}));
    }
    host.append(el('p', {class: 'muted small', text:
      'Shown: text extracted from the uploaded file. Highlighted text is the passage the AI cited.'}),
      futureButton('Open original file',
        'Opening the private original PDF/DOCX will be available after staff access is implemented.'));
  }

  function coverage(report) {
    return report.sections.filter(s => s.key !== 'sources').map(section => {
      const blocks = section.blocks.filter(b => b.kind !== 'note');
      const items = blocks.flatMap(b => b.items);
      const notes = section.blocks.filter(b => b.kind === 'note').map(b => b.text).join(' ');
      const cites = new Set(items.flatMap(i => i.citations));
      let state;
      if (!items.length) state = /no separate description/i.test(notes) ? 'partial' : 'missing';
      else if (cites.size) state = /not documented|no separate description/i.test(notes) ? 'partial' : 'documented';
      else state = 'interpretation';
      return {section, state, cites: cites.size};
    });
  }

  const COVERAGE = {
    documented: ['Supported by documents', 'good'],
    partial: ['Partly documented', 'warn'],
    interpretation: ['AI interpretation only', 'info'],
    missing: ['Not documented', 'bad']};

  function claimLine(claim, ws, fallback) {
    if (!claim || !claim.value) return el('p', {class: 'doc-note', text: fallback || 'Not documented in the uploaded materials.'});
    const kind = (claim.explanation || '').startsWith('UNVERIFIED') ? badge('⚠ Unverified', 'warn')
      : claim.classification === 'document_fact' ? badge('From documents', 'good')
      : claim.classification === 'registration_fact' ? badge('Declared at registration', 'neutral')
      : badge('AI interpretation', 'info');
    return el('p', {}, claim.value, citeButtons(ws.cite(claim.evidence), ws), ' ', kind);
  }

  function claimList(claims, ws, empty) {
    const present = (claims || []).filter(c => c && c.value);
    if (!present.length) return el('p', {class: 'doc-note', text: empty});
    return el('ul', {class: 'compact'},
      present.map(c => el('li', {}, Array.from(claimLine(c, ws).childNodes))));
  }

  function fieldName(path) {
    const text = path.split('.').pop().replace(/_/g, ' ');
    return (text[0].toUpperCase() + text.slice(1)).replace(/\btrl\b/i, 'TRL');
  }

  function renderEvidencePanel(ws) {
    const p = ws.sample.profile;
    const panel = el('section', {class: 'evidence-panel', 'aria-labelledby': 'evidence-heading'},
      el('h2', {id: 'evidence-heading', class: 'panel-title', text: 'Original document evidence'}));

    const viewer = el('div', {class: 'evidence-viewer', id: 'evidence-viewer', tabindex: '-1',
                              'aria-live': 'polite'});
    ws.viewer = viewer;
    renderEvidenceViewer(ws, viewer);

    const citedPerFile = file => ws.report.sources.filter(s => s.source_file === file).length;
    panel.append(
      el('h3', {text: 'Source documents'}),
      el('ul', {class: 'doc-list'}, ws.sample.documents.map(d => el('li', {},
        el('span', {class: 'doc-name', text: d.filename}), ' ', relevanceBadge(d.relevance),
        el('span', {class: 'muted small', text: ` ${citedPerFile(d.filename)} cited location(s)`}),
        el('button', {type: 'button', class: 'btn small', text: 'View text',
                      'aria-label': `View extracted text of ${d.filename}`,
                      onclick: () => ws.showDocument(d.filename)})))),
      el('h3', {text: 'Evidence viewer'}), viewer);

    // Registration details vs the AI report
    const reg = ws.item;
    const reportInventors = (p.identity.inventors || []).map(c => c.value).filter(Boolean);
    const same = (a, b) => String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase();
    const compareRows = [
      ['Title', reg.title, p.identity.title && p.identity.title.value],
      ['Lead inventor', reg.inventor, reportInventors.join('; ')],
      ['Technical domain', reg.domain, p.technology.primary_domain && p.technology.primary_domain.value],
      ['Declared TRL', reg.declaredTrl ? `TRL ${reg.declaredTrl}` : '—',
       p.readiness.reported_trl ? `TRL ${p.readiness.reported_trl}` : '—']];
    panel.append(el('h3', {text: 'Registration details vs AI report'}),
      el('table', {class: 'coverage-table'},
        el('thead', {}, el('tr', {}, ['Field', 'Registration', 'AI report', 'Check']
          .map(h => el('th', {scope: 'col', text: h})))),
        el('tbody', {}, compareRows.map(([field, a, b]) => {
          const ok = field === 'Lead inventor' ? String(b || '').toLowerCase().includes(String(a).toLowerCase())
            : same(a, b);
          return el('tr', {}, el('th', {scope: 'row', text: field}), el('td', {text: a || '—'}),
            el('td', {text: b || '—'}), el('td', {}, ok ? badge('Consistent', 'good') : badge('Differs', 'warn')));
        }))),
      el('p', {class: 'muted small', text:
        'Compare the AI report, the original documents and the registration. Differences are ' +
        'for the reviewer to resolve with the innovator.'}));

    // Coverage
    const rows = coverage(ws.report);
    panel.append(el('h3', {text: 'Document coverage by report section'}),
      el('table', {class: 'coverage-table'},
        el('thead', {}, el('tr', {}, ['Section', 'Coverage', 'Cited sources']
          .map(h => el('th', {scope: 'col', text: h})))),
        el('tbody', {}, rows.map(({section, state, cites}) => el('tr', {},
          el('th', {scope: 'row'}, el('button', {type: 'button', class: 'link-button',
            onclick: () => ws.showSection(section.number)}, `${section.number}. ${section.title}`)),
          el('td', {}, badge(...COVERAGE[state])),
          el('td', {text: String(cites)}))))));

    // Contradictions and missing information
    const gaps = ws.report.sections.find(s => s.key === 'gaps_next_steps');
    const listBlock = heading => (gaps.blocks.find(b => b.heading === heading) || {items: []}).items;
    panel.append(el('h3', {text: 'Contradictions and discrepancies'}),
      p.discrepancies.length ? el('ul', {class: 'alert-list'}, p.discrepancies.map(d => el('li', {},
        badge(d.kind === 'between_documents' ? 'Unresolved contradiction' : 'Registration vs documents', 'warn'),
        ' ', el('strong', {text: fieldName(d.field)}), ': ',
        d.kind === 'between_documents'
          ? `“${d.document_value}” versus “${d.other_document_value}”`
          : `registration states “${d.registration_value}”, documents state “${d.document_value}”`,
        citeButtons(ws.cite(d.evidence), ws))))
        : el('p', {class: 'doc-note', text: 'No contradictions were recorded by the AI. Check the documents anyway.'}),
      el('h3', {text: 'Missing or partly documented information'}),
      el('ul', {class: 'alert-list'},
        listBlock('Partly documented').map(i => el('li', {}, badge('Partly documented', 'warn'), ' ', i.text)),
        listBlock('Information not documented in the uploaded materials')
          .map(i => el('li', {}, badge('Not documented', 'bad'), ' ', i.text))));

    // Results and limitations
    panel.append(el('h3', {text: 'Experimental results and technical limitations'}),
      el('h4', {text: 'Testing methods'}),
      claimList(p.development.testing_methods, ws, 'No testing methods were extracted.'),
      el('h4', {text: 'Experimental results'}),
      claimList(p.development.experimental_results, ws, 'No experimental results were extracted.'),
      el('h4', {text: 'Technical limitations'}),
      claimList(p.development.technical_limitations, ws, 'No limitations were extracted.'));

    // TRL, three separate values
    const trlSelect = el('select', {id: 'reviewer-trl', onchange: e => { ws.state.trl = e.target.value; }},
      el('option', {value: '', text: 'Not assessed yet'}),
      [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => el('option', {value: String(n), text: `TRL ${n}`,
                                                       selected: ws.state.trl === String(n)})));
    panel.append(el('h3', {text: 'Technology readiness (TRL)'}),
      el('div', {class: 'trl-grid'},
        el('div', {class: 'trl-tile'}, el('span', {class: 'trl-kind', text: 'Declared by innovator'}),
          el('strong', {text: p.readiness.reported_trl ? `TRL ${p.readiness.reported_trl}` : 'Not declared'}),
          el('span', {class: 'muted small', text: 'From the registration form'})),
        el('div', {class: 'trl-tile'}, el('span', {class: 'trl-kind', text: 'AI-estimated'}),
          el('strong', {text: p.readiness.suggested_trl ? `TRL ${p.readiness.suggested_trl}` : 'Not estimated'}),
          el('span', {class: 'muted small', text: 'Indicative only; not a certification'})),
        el('div', {class: 'trl-tile reviewer'},
          el('label', {class: 'trl-kind', for: 'reviewer-trl', text: 'Staff-assessed'}), trlSelect,
          el('span', {class: 'muted small', text: 'Not saved in this phase'}))),
      el('h4', {text: 'AI justification'}),
      claimLine(p.readiness.justification, ws, 'No TRL justification was extracted.'));

    // IP and ownership
    const ip = p.intellectual_property;
    panel.append(el('h3', {text: 'IP and ownership evidence'}),
      el('h4', {text: 'Patent status'}), claimLine(ip.patent_status, ws),
      el('h4', {text: 'Ownership'}), claimLine(ip.ownership_claims, ws,
        'Ownership is not documented in the uploaded materials.'),
      el('h4', {text: 'Licensing restrictions'}),
      claimList(ip.licensing_restrictions, ws, 'None documented.'),
      el('p', {class: 'muted small', text:
        'Filing and ownership statements are reported as written in the documents. They are ' +
        'not legal confirmation of patent status or ownership.'}));
    return panel;
  }

  function renderAssessment(ws) {
    const checklist = ICData.checklist();
    const checkStates = ICData.checkStates();
    const status = ws.item.status;
    const progress = el('p', {class: 'progress', 'aria-live': 'polite'});
    const updateProgress = () => {
      const done = checklist.filter(c => (ws.state.checks[c.id] || 'unchecked') !== 'unchecked').length;
      progress.textContent = `${done} of ${checklist.length} checklist items assessed`;
    };

    const panel = el('section', {class: 'assessment-panel', 'aria-labelledby': 'assessment-heading'},
      el('h2', {id: 'assessment-heading', class: 'panel-title', text: 'Reviewer assessment'}),
      el('div', {class: 'preview-callout', role: 'note'},
        el('strong', {text: 'Not saved: '}),
        'in this development phase your choices stay on this screen only and disappear when ',
        'you leave or reload the page.'),
      el('h3', {text: 'Three kinds of evidence status'}),
      el('dl', {class: 'evidence-kinds'},
        el('dt', {}, badge('Supported by uploaded documents', 'good')),
        el('dd', {text: 'The statement appears in the innovator\'s uploaded documents. The AI ' +
                        'cited it; this shows the documents say it, not that it is true.'}),
        el('dt', {}, badge('Independently validated by the institution', 'neutral')),
        el('dd', {text: 'A reviewer has confirmed it independently (for example by inspecting ' +
                        'the prototype or test records). Recorded only through the future ' +
                        'review workflow.'}),
        el('dt', {}, badge('Unverified or insufficient evidence', 'warn')),
        el('dd', {text: 'The AI could not confirm the quoted passage, or the documents do not ' +
                        'contain enough evidence. Ask the innovator before relying on it.'})),
      el('h3', {text: 'Human verification checklist'}), progress);

    checklist.forEach((item, index) => {
      const group = `check-${item.id}`;
      const fieldset = el('fieldset', {class: 'check-item'},
        el('legend', {text: `${index + 1}. ${item.title}`}),
        el('p', {class: 'muted small', text: item.check}),
        item.sections.length ? el('p', {class: 'small section-links'}, 'Report sections: ',
          item.sections.map(n => el('button', {type: 'button', class: 'link-button',
            text: String(n), 'aria-label': `Go to report section ${n}`,
            onclick: () => ws.showSection(n)}))) : null);
      if (item.id !== 'conclusion') {
        fieldset.append(el('div', {class: 'radio-row'}, checkStates.map(state => {
          const id = `${group}-${state.value}`;
          return el('label', {for: id, class: 'radio'},
            el('input', {type: 'radio', id, name: group, value: state.value,
                         checked: (ws.state.checks[item.id] || 'unchecked') === state.value,
                         onchange: () => { ws.state.checks[item.id] = state.value; updateProgress(); }}),
            state.label);
        })));
      }
      const noteId = `${group}-note`;
      fieldset.append(el('label', {for: noteId, class: 'small',
                                   text: item.id === 'conclusion' ? 'Conclusion and reasons' : 'Note (optional)'}),
        el('textarea', {id: noteId, rows: item.id === 'conclusion' ? 4 : 2,
                        oninput: e => {
                          ws.state.notes[item.id] = e.target.value;
                          if (item.id === 'conclusion') {
                            ws.state.checks.conclusion = e.target.value.trim() ? 'supported' : 'unchecked';
                            updateProgress();
                          }
                        }}, ws.state.notes[item.id] || ''));
      panel.append(fieldset);
    });
    updateProgress();

    panel.append(
      el('h3', {text: 'Reviewer notes'}),
      el('label', {for: 'reviewer-notes', class: 'sr-only', text: 'Reviewer notes'}),
      el('textarea', {id: 'reviewer-notes', rows: 4,
                      placeholder: 'General notes for colleagues (preview — not saved)',
                      oninput: e => { ws.state.general = e.target.value; }}, ws.state.general || ''),
      el('h3', {text: 'Verification status'}),
      el('dl', {class: 'status-dl'},
        el('dt', {text: 'Submission'}), el('dd', {}, badge('Innovator-submitted', 'neutral'),
          ' Not institutionally verified.'),
        el('dt', {text: 'Review status'}), el('dd', {}, badge(status.label, status.tone), ' ', status.help),
        el('dt', {text: 'Institutional validation'}), el('dd', {text: 'None recorded.'})),
      el('h3', {text: 'Review outcome (future)'}),
      el('p', {class: 'muted small', text:
        'Only an authorised reviewer will be able to record an outcome, with reasons, after ' +
        'staff access is implemented. Nothing can be approved or rejected yet.'}),
      el('div', {class: 'outcomes'},
        futureButton('Verified', null, 'innovation_center.profiles.approve'),
        futureButton('Request clarification', null, 'innovation_center.profiles.request_correction'),
        futureButton('Rejected / On hold', null, 'innovation_center.profiles.reject')),
      el('p', {class: 'muted small', text:
        'An innovator submission never becomes institutionally verified automatically.'}));
    return panel;
  }

  function renderWorkspace(main, id) {
    const item = ICData.invention(id);
    const back = el('p', {}, el('a', {href: 'profile-approvals.html', class: 'back-link',
                                      text: '← Back to review queue'}));
    if (!item) {
      main.append(back, el('h1', {text: 'Submission not found'}),
                  el('p', {class: 'muted', text: 'This sample record does not exist.'}));
      return;
    }
    const status = item.status;
    main.append(back,
      el('h1', {text: item.title}),
      el('dl', {class: 'meta-row'},
        ...[['Inventor', item.inventor], ['Technical domain', item.domain],
            ['Confidentiality', item.confidentiality], ['Submitted', formatDate(item.submitted)]]
          .map(([k, v]) => el('div', {}, el('dt', {text: k}), el('dd', {text: v}))),
        el('div', {}, el('dt', {text: 'Verification status'}),
           el('dd', {}, badge(status.label, status.tone)))),
      el('p', {class: 'submission-note'}, badge('Innovator-submitted — not institutionally verified', 'warn')),
      demoLabel('Fictional sample submission.'));

    const sample = item.sample && ICData.samples()[item.sample];
    if (!sample) {
      main.append(el('p', {class: 'doc-note', text:
        'This sample record has no generated report in the demo data. Open RainLattice R3 or ' +
        'Tidewell to see a complete review workspace.'}));
      return;
    }

    const ws = {item, sample, report: sample.report, selection: null,
                state: {checks: {}, notes: {}, trl: '', general: ''}};
    ws.cite = sourceIndex(ws.report);

    const tabs = [['report', 'Report'], ['evidence', 'Evidence'], ['assessment', 'Assessment']];
    const panels = {
      report: el('div', {class: 'ws-panel', id: 'panel-report', role: 'tabpanel',
                         'aria-labelledby': 'tab-report'}, renderReport(ws)),
      evidence: el('div', {class: 'ws-panel', id: 'panel-evidence', role: 'tabpanel',
                           'aria-labelledby': 'tab-evidence'}, renderEvidencePanel(ws)),
      assessment: el('div', {class: 'ws-panel', id: 'panel-assessment', role: 'tabpanel',
                             'aria-labelledby': 'tab-assessment'}, renderAssessment(ws))};
    const tabButtons = tabs.map(([key, label]) => el('button', {
      type: 'button', role: 'tab', id: `tab-${key}`, 'aria-controls': `panel-${key}`, text: label,
      onclick: () => activate(key, true),
      onkeydown: e => {
        const i = tabs.findIndex(t => t[0] === key);
        const next = e.key === 'ArrowRight' ? (i + 1) % tabs.length
          : e.key === 'ArrowLeft' ? (i + tabs.length - 1) % tabs.length
          : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null;
        if (next !== null) { e.preventDefault(); activate(tabs[next][0], true); }
      }}));
    function activate(key, focusTab) {
      tabs.forEach(([k], i) => {
        const on = k === key;
        tabButtons[i].setAttribute('aria-selected', String(on));
        tabButtons[i].tabIndex = on ? 0 : -1;
        panels[k].classList.toggle('active', on);
      });
      if (focusTab) tabButtons[tabs.findIndex(t => t[0] === key)].focus();
    }
    const narrow = () => window.matchMedia('(max-width: 1099px)').matches;

    ws.showSource = n => {
      ws.selection = {source: ws.report.sources[n - 1]};
      renderEvidenceViewer(ws, ws.viewer);
      if (narrow()) activate('evidence');
      ws.viewer.focus({preventScroll: true});
      ws.viewer.scrollIntoView({block: 'start'});
    };
    ws.showDocument = file => {
      ws.selection = {file};
      renderEvidenceViewer(ws, ws.viewer);
      ws.viewer.focus({preventScroll: true});
      ws.viewer.scrollIntoView({block: 'start'});
    };
    ws.showSection = n => {
      if (narrow()) activate('report');
      const target = document.getElementById(`sec-${n}`);
      if (target) { target.scrollIntoView({block: 'start'}); target.focus({preventScroll: true}); }
    };

    main.append(
      el('div', {class: 'ws-tabs', role: 'tablist', 'aria-label': 'Review workspace'}, tabButtons),
      el('div', {class: 'workspace'},
        el('div', {class: 'ws-left'}, panels.report),
        el('div', {class: 'ws-right'}, panels.evidence, panels.assessment)));
    activate('report');
  }

  page(main => {
    const id = param('review');
    main.classList.toggle('wide', !!id);
    if (id) renderWorkspace(main, id); else renderQueue(main);
  });
})();
