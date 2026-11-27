// Administrator module — Roles & Access.
// A local, in-memory permission draft. Nothing is persisted, assigned or
// sent; no real permission policy is read or written.
(function () {
  'use strict';
  const {el, onReady} = window.AdminUI;

  const ROLES = [
    {id: 'administrator', label: 'Administrator',
     text: 'Full platform administration, including users, roles, organizations, agents and configuration.'},
    {id: 'admin-employee', label: 'Admin Employee',
     text: 'Permission-based subrole within the Administrator module. Receives only the administrative ' +
           'permissions an Administrator grants.'},
    {id: 'innovator', label: 'Innovator',
     text: 'Researchers who register inventions and submit invention profiles.'},
    {id: 'innovation-center', label: 'Innovation Center',
     text: 'Staff who verify invention profiles and review the portfolio.'},
    {id: 'industry-liaison', label: 'Industry Liaison',
     text: 'Staff who review industry matches and manage partner outreach.'},
    {id: 'management', label: 'Management',
     text: 'Executives who view reports and pipeline status.'},
    {id: 'external-partner', label: 'External Partner',
     text: 'Organizations invited to view shared opportunities.'}
  ];

  const PERMISSIONS = [
    ['view', 'Viewing records'], ['create', 'Creating records'], ['edit', 'Editing records'],
    ['delete', 'Deleting records'], ['approve', 'Approving information'],
    ['users', 'Managing users'], ['roles', 'Managing roles'],
    ['organizations', 'Managing organizations'], ['agents', 'Executing agents'],
    ['inventions', 'Reviewing invention profiles'], ['matches', 'Reviewing industry matches'],
    ['outreach', 'Managing outreach'], ['reports', 'Viewing reports'],
    ['config', 'Managing system configuration']
  ];

  // draft[roleId][permId] = true | false; missing = not configured.
  const draft = Object.fromEntries(ROLES.map(r => [r.id, {}]));
  let selected = ROLES[0].id;

  function renderMatrix() {
    document.getElementById('matrixHead').replaceChildren(el('tr', {},
      el('th', {scope: 'col', text: 'Permission'}),
      ROLES.map(r => el('th', {scope: 'col', class: r.id === selected ? 'col-selected' : null,
                               text: r.label}))));
    document.getElementById('matrixBody').replaceChildren(...PERMISSIONS.map(([pid, label]) =>
      el('tr', {},
        el('th', {scope: 'row', text: label}),
        ROLES.map(r => {
          const value = draft[r.id][pid];
          const cls = (r.id === selected ? 'col-selected ' : '') +
            (value === undefined ? 'cell-unset' : value ? 'cell-draft-on' : 'cell-draft-off');
          const text = value === undefined ? '—' : value ? 'Allowed (draft)' : 'Not allowed (draft)';
          return el('td', {class: cls},
            value === undefined ? el('span', {'aria-hidden': 'true', text}) : text,
            value === undefined ? el('span', {class: 'sr-only', text: 'Not configured'}) : null);
        }))));
  }

  function renderChecks() {
    const role = ROLES.find(r => r.id === selected);
    document.getElementById('roleDescription').textContent = role.text;
    document.getElementById('permLegend').textContent = 'Permissions for ' + role.label;
    document.getElementById('permChecks').replaceChildren(...PERMISSIONS.map(([pid, label]) => {
      const id = 'perm-' + pid;
      return el('li', {}, el('label', {class: 'check', for: id},
        el('input', {type: 'checkbox', id, checked: draft[selected][pid] === true,
                     onchange: e => { draft[selected][pid] = e.target.checked; update(); }}),
        label));
    }));
  }

  function update() {
    const changed = Object.values(draft).reduce((n, perms) => n + Object.keys(perms).length, 0);
    document.getElementById('draftStatus').textContent = changed
      ? `${changed} local draft change(s). Not saved — saving permissions is not connected.`
      : 'No draft changes.';
    renderMatrix();
  }

  onReady(() => {
    const select = document.getElementById('roleSelect');
    select.replaceChildren(...ROLES.map(r => el('option', {value: r.id, text: r.label})));
    select.addEventListener('change', () => { selected = select.value; renderChecks(); update(); });
    document.getElementById('resetRole').addEventListener('click', () => {
      draft[selected] = {};
      renderChecks();
      update();
    });
    renderChecks();
    update();
  });
})();
