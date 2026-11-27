// Administrator module — sidebar navigation.
// Renders the primary sections the caller may open into
// <aside id="adminSidebar">. Which pages are open comes from the server
// (GET /admin/session -> pages), computed from the backend permission
// registry; the server also refuses any other page if it is requested
// directly. The current section comes from <body data-section>; detail pages
// (Organization Profile, Approval Review) also set data-subpage.
(function () {
  'use strict';
  const {el, onReady} = window.AdminUI;

  const SECTIONS = [
    {id: 'overview', label: 'Overview', href: 'overview.html'},
    {id: 'users', label: 'User Management', href: 'user-management.html'},
    {id: 'roles', label: 'Roles & Access', href: 'roles-access.html'},
    {id: 'organizations', label: 'Organizations', href: 'organizations.html',
     sub: {id: 'organization-profile', label: 'Organization Profile',
           href: 'organization-profile.html'}},
    {id: 'approvals', label: 'Data Approvals', href: 'data-approvals.html',
     sub: {id: 'approval-review', label: 'Approval Review', href: 'approval-review.html'}},
    {id: 'agents', label: 'Agent Control', href: 'agent-control.html'},
    {id: 'sources', label: 'Data Sources', href: 'data-sources.html'},
    {id: 'audit', label: 'Audit Logs', href: 'audit-logs.html'}
  ];

  function accessSummary(session) {
    const expires = new Date(session.expires_at * 1000);
    return el('dl', {class: 'access-summary'},
      el('dt', {text: 'Role'}), el('dd', {text: session.roleLabel}),
      el('dt', {text: 'Account status'}), el('dd', {text: 'Active'}),
      el('dt', {text: 'Session ends'}),
      el('dd', {text: expires.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}),
      el('dt', {text: 'Permissions'}),
      el('dd', {},
        `${session.permissions.length}`,
        el('details', {},
          el('summary', {text: 'Show permissions'}),
          session.permissions.length
            ? el('ul', {}, session.permissions.map(p => el('li', {text: p})))
            : el('p', {class: 'small muted', text: 'No permissions are assigned yet.'}))));
  }

  onReady(session => {
    const host = document.getElementById('adminSidebar');
    if (!host) return;
    const section = document.body.dataset.section;
    const subpage = document.body.dataset.subpage;

    const nav = el('nav', {class: 'side-nav adm-nav', 'aria-label': 'Administrator'});
    for (const s of SECTIONS) {
      if (session.pages[s.href] !== true) continue;
      const onSection = s.id === section;
      const link = el('a', {href: s.href, 'data-section': s.id, text: s.label});
      if (onSection && !subpage) link.setAttribute('aria-current', 'page');
      else if (onSection) link.classList.add('section-current');
      nav.append(link);
      if (s.sub && onSection && subpage === s.sub.id && session.pages[s.sub.href] === true) {
        nav.append(el('a', {href: s.sub.href, class: 'nav-sub', 'aria-current': 'page',
                            text: '↳ ' + s.sub.label}));
      }
    }
    nav.append(el('a', {href: '/dashboard', class: 'nav-back', text: '← Back to Innovator'}));

    host.replaceChildren(
      el('div', {class: 'role-card'},
        el('strong', {text: session.roleLabel}),
        el('p', {class: 'muted small', style: 'margin:4px 0 0', text: 'Platform administration'}),
        accessSummary(session)),
      nav);
  });

  window.AdminNav = {sections: SECTIONS.map(s => ({...s}))};
})();
