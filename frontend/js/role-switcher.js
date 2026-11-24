// Development-stage interface switcher (presentation only).
//
// It changes which interface is SHOWN; it is not an institutional role
// assignment, reads and writes no permissions, and grants no data access.
// The current interface comes from <body data-role="...">, so a page refresh
// keeps it. Real staff roles will be enforced server-side in a later phase.
(function () {
  'use strict';

  const ROLES = [
    {id: 'innovator', label: 'Innovator / Researcher', href: '/dashboard'},
    {id: 'innovation-center', label: 'Innovation Center',
     href: '/assets/roles/innovation-center/index.html'},
    {id: 'industry-liaison', label: 'Industry Liaison Office',
     href: '/assets/roles/industry-liaison/index.html', comingSoon: true},
    {id: 'management', label: 'Management / Executive',
     href: '/assets/roles/management/index.html', comingSoon: true},
    {id: 'administrator', label: 'Administrator',
     href: '/assets/roles/administrator/index.html', comingSoon: true},
    {id: 'industry-partner', label: 'Industry Partner',
     href: '/assets/roles/industry-partner/index.html', comingSoon: true}
  ];

  function build(host) {
    const current = ROLES.find(r => r.id === document.body.dataset.role) || ROLES[0];
    const menuId = 'role-switcher-menu';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'role-switcher-button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', menuId);
    const small = document.createElement('span');
    small.className = 'role-switcher-kicker';
    small.textContent = 'Switch role';
    const name = document.createElement('span');
    name.className = 'role-switcher-current';
    name.textContent = current.label;
    const caret = document.createElement('span');
    caret.setAttribute('aria-hidden', 'true');
    caret.textContent = ' ▾';
    button.append(small, name, caret);

    const panel = document.createElement('div');
    panel.id = menuId;
    panel.className = 'role-switcher-panel';
    panel.hidden = true;

    const list = document.createElement('ul');
    list.setAttribute('aria-label', 'Interfaces');
    for (const role of ROLES) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = role.href;
      link.dataset.roleId = role.id;
      link.textContent = role.label;
      if (role.id === current.id) {
        link.setAttribute('aria-current', 'page');
        const tag = document.createElement('span');
        tag.className = 'role-tag current';
        tag.textContent = 'Current';
        link.append(' ', tag);
      } else if (role.comingSoon) {
        const tag = document.createElement('span');
        tag.className = 'role-tag soon';
        tag.textContent = 'Coming soon';
        link.append(' ', tag);
      }
      item.append(link);
      list.append(item);
    }
    const note = document.createElement('p');
    note.className = 'role-switcher-note';
    note.textContent = 'Development switcher: changes the interface only. It is not an ' +
      'institutional role and gives no access to other users\' data.';
    panel.append(list, note);

    const close = (focusButton) => {
      panel.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      if (focusButton) button.focus();
    };
    button.addEventListener('click', () => {
      const open = panel.hidden;
      panel.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
      if (open) (list.querySelector('a[aria-current]') || list.querySelector('a')).focus();
    });
    host.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); close(true); }
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !panel.hidden) {
        const links = [...list.querySelectorAll('a')];
        const index = links.indexOf(document.activeElement);
        const next = event.key === 'ArrowDown' ? (index + 1) % links.length
          : (index - 1 + links.length) % links.length;
        event.preventDefault();
        links[next].focus();
      }
    });
    document.addEventListener('click', event => {
      if (!panel.hidden && !host.contains(event.target)) close(false);
    });

    host.classList.add('role-switcher');
    host.replaceChildren(button, panel);
  }

  window.PROFILE_MATCH_ROLES = ROLES.map(r => ({...r}));
  document.addEventListener('DOMContentLoaded', () => {
    const host = document.getElementById('roleSwitcher');
    if (host) build(host);
  });
})();
