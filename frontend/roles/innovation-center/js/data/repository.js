// Innovation Center data access (the ONLY place pages read data from).
//
// Today it reads the fictional window.IC_MOCK_DATA. A later phase replaces
// these functions with authorised staff API calls; pages stay unchanged.
// It deliberately provides NO statistics or analytics: summary figures and
// trends stay placeholders until real data is integrated.
(function () {
  'use strict';
  const D = window.IC_MOCK_DATA;
  const STAGE_INDEX = Object.fromEntries(D.stages.map((s, i) => [s.id, i]));

  const copy = value => JSON.parse(JSON.stringify(value));
  const criterionLabel = id => D.criteria.find(c => c.id === id).label;

  function days(from, to) {
    return Math.round((Date.parse(to + 'T00:00:00Z') - Date.parse(from + 'T00:00:00Z')) / 86400000);
  }

  // Strongest criterion = the highest of the six displayed values.
  function strongest(scores) {
    let best = null;
    for (const c of D.criteria) {
      if (best === null || scores[c.id] > best.value) best = {id: c.id, label: c.label, value: scores[c.id]};
    }
    return best;
  }

  function matchesFor(id) {
    return copy(D.matches[id] || [])
      .sort((a, b) => b.overall - a.overall)
      .map((m, i) => ({...m, rank: i + 1, strongest: strongest(m.scores)}));
  }

  function enrich(inv) {
    const matches = matchesFor(inv.id);
    return {...copy(inv), stageIndex: STAGE_INDEX[inv.stage],
            stageLabel: D.stages[STAGE_INDEX[inv.stage]].label,
            status: D.reviewStatuses[inv.reviewStatus],
            matches, matched: matches.length > 0, top: matches[0] || null};
  }

  const inventions = () => D.inventions.map(enrich);
  const invention = id => { const inv = D.inventions.find(i => i.id === id); return inv ? enrich(inv) : null; };

  function recentActivity(limit) {
    return inventions().sort((a, b) => b.latest.date.localeCompare(a.latest.date) || a.id.localeCompare(b.id))
      .slice(0, limit || 6)
      .map(i => ({date: i.latest.date, text: i.latest.text, invention: i.title, id: i.id}));
  }

  function pendingReviews() {
    return inventions().filter(i => i.reviewStatus === 'awaiting' || i.reviewStatus === 'in_review')
      .sort((a, b) => a.submitted.localeCompare(b.submitted))
      .map(i => ({...i, waitingDays: days(i.submitted, D.asOf)}));
  }

  // Inventions needing staff attention, each with plain-language reasons.
  function attention() {
    return inventions().map(i => {
      const reasons = [...i.flags];
      if (i.reviewStatus === 'clarification') reasons.unshift('Waiting for innovator clarification');
      if (i.reviewStatus === 'on_hold') reasons.unshift('Rejected / on hold');
      if (i.declaredTrl && i.aiTrl && Math.abs(i.declaredTrl - i.aiTrl) >= 2) {
        reasons.push(`Declared TRL ${i.declaredTrl} vs AI-estimated TRL ${i.aiTrl}`);
      }
      if (i.reviewStatus === 'awaiting' && days(i.submitted, D.asOf) > 14) {
        reasons.push(`Waiting ${days(i.submitted, D.asOf)} days for review`);
      }
      return {...i, reasons};
    }).filter(i => i.reasons.length);
  }

  window.ICData = {
    raw: D, inventions, invention, matchesFor, strongest, criterionLabel, recentActivity,
    pendingReviews, attention, reviewQueue: () => inventions().filter(i => i.submitted),
    stages: () => copy(D.stages), statuses: () => copy(D.reviewStatuses),
    criteria: () => copy(D.criteria), checklist: () => copy(D.checklist),
    checkStates: () => copy(D.checkStates), asOf: () => D.asOf,
    samples: () => window.IC_SAMPLE_REPORTS || {}
  };
})();
