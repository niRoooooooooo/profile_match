// Innovation Center — Overview.
// No charts or statistics in this phase: summary figures and trends show
// placeholders until real database and agent data is connected. The work
// lists below use the same fictional sample submissions as Profile approvals.
(function () {
  'use strict';
  const {el, demoLabel, badge, formatDate, page, trendsPlaceholders, notAvailable,
         can} = window.ICShell;
  const ICData = window.ICData;

  const SUMMARY = ['Total inventions', 'Profiles awaiting institutional review',
                   'Institutionally verified inventions', 'Inventions requiring clarification',
                   'Rejected or on-hold inventions', 'Inventions in the matching stage',
                   'Active industry engagements'];

  page(main => {
    main.append(
      el('div', {class: 'page-head'},
        el('div', {}, el('h1', {text: 'Innovation Center overview'}),
          el('p', {class: 'lead', text:
            'Where inventions stand, what needs a staff decision, and how verified inventions ' +
            'progress towards industry partners.'})),
        el('nav', {class: 'quick-links', 'aria-label': 'Quick navigation'},
          el('a', {class: 'btn small', href: 'profile-approvals.html', text: 'Open Profile approvals'}),
          el('a', {class: 'btn small', href: 'portfolio.html', text: 'Open Portfolio'}))),

      el('section', {'aria-labelledby': 'summary-h'},
        el('h2', {id: 'summary-h', class: 'section-title', text: 'Portfolio summary'}),
        el('p', {class: 'small muted', text:
          'These figures will be calculated from real invention records after data integration. ' +
          'No numbers are shown until then.'}),
        el('ul', {class: 'kpi-grid', 'aria-label': 'Summary statistics (not available yet)'},
          SUMMARY.map(notAvailable))),

      trendsPlaceholders());

    // Work lists (sample records, the same ones shown in Profile approvals).
    // Shown only to accounts that may view inventions.
    if (!can('innovation_center.inventions.view')) return;
    const pending = ICData.pendingReviews();
    const attention = ICData.attention();
    const activity = ICData.recentActivity(6);
    const reviewLink = inv => el('a', {href: `profile-approvals.html?review=${inv.id}`, text: inv.title});
    main.append(
      el('h2', {class: 'section-title', text: 'Work queue'}),
      demoLabel('Fictional sample submissions — the same records shown in Profile approvals.'),
      el('div', {class: 'two-col'},
        el('section', {class: 'panel', 'aria-labelledby': 'pending-h'},
          el('h2', {id: 'pending-h', text: 'Pending verification tasks'}),
          el('p', {class: 'small muted', text: 'Oldest first. Submitted reports waiting for staff review.'}),
          pending.length ? el('ul', {class: 'plain-list'}, pending.map(inv => el('li', {}, reviewLink(inv), ' ',
            badge(inv.status.label, inv.status.tone),
            el('span', {class: 'meta', text: `Submitted ${formatDate(inv.submitted)} · ${inv.domain}`}))))
            : el('p', {class: 'doc-note', text: 'No submissions are waiting for review.'})),
        el('section', {class: 'panel', 'aria-labelledby': 'attention-h'},
          el('h2', {id: 'attention-h', text: 'Inventions requiring attention'}),
          attention.length ? el('ul', {class: 'plain-list'}, attention.map(inv => el('li', {},
            inv.submitted ? reviewLink(inv) : el('strong', {text: inv.title}), ' ',
            badge(inv.status.label, inv.status.tone),
            el('span', {class: 'meta', text: inv.reasons.join(' · ')}))))
            : el('p', {class: 'doc-note', text: 'Nothing needs attention.'}))),
      el('section', {class: 'panel', style: 'margin-top:22px', 'aria-labelledby': 'activity-h'},
        el('h2', {id: 'activity-h', text: 'Recent review activity'}),
        el('ul', {class: 'plain-list'}, activity.map(a => el('li', {},
          el('time', {datetime: a.date, class: 'meta', text: formatDate(a.date)}),
          el('strong', {text: a.invention}), ' — ', a.text)))));
  });
})();
