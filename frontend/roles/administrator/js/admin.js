// Administrator module — shared UI helpers and page authorization.
//
// The only network request is GET/DELETE /admin/session (the caller's own
// server-verified administrative session). Tabs, dialogs, local file
// selection, form checks and filters stay local to the browser tab: nothing
// is saved, uploaded or sent, and no privileged operation is ever reported as
// successful. Unfinished operations are rendered disabled and labelled
// "Not connected".
(function () {
  'use strict';

  const NOT_CONNECTED = 'Not connected — available after backend integration.';

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

  const badge = (text, tone) => el('span', {class: 'badge tone-' + (tone || 'neutral'), text});

  // A visible-but-disabled control for an operation that is not connected.
  let ncCount = 0;
  function ncButton(label, note, extraClass) {
    const id = 'nc-note-' + (++ncCount);
    return el('span', {class: 'nc-control'},
      el('button', {type: 'button', class: 'btn small ' + (extraClass || ''), disabled: true,
                    'aria-disabled': 'true', 'aria-describedby': id, text: label}),
      el('span', {id, class: 'nc-note', text: note || NOT_CONNECTED}));
  }

  // Static markup: <button data-nc="optional note">Label</button> becomes a
  // disabled control with a visible explanation.
  function enhanceNotConnected(root) {
    for (const button of root.querySelectorAll('button[data-nc]')) {
      if (button.dataset.ncDone) continue;
      button.dataset.ncDone = '1';
      const id = 'nc-note-' + (++ncCount);
      button.type = 'button';
      button.classList.add('btn', 'small');
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
      button.setAttribute('aria-describedby', id);
      const wrap = el('span', {class: 'nc-control'});
      button.replaceWith(wrap);
      wrap.append(button, el('span', {id, class: 'nc-note', text: button.dataset.nc || NOT_CONNECTED}));
    }
  }

  // Table body with one full-width empty-state row.
  function emptyRow(tbody, colspan, title, text) {
    tbody.replaceChildren(el('tr', {},
      el('td', {class: 'empty-cell', colspan: String(colspan)},
        el('strong', {text: title}), text)));
  }

  // ---------------------------------------------------------------- dialogs
  // <button data-open-dialog="id"> opens <dialog id>; [data-close-dialog]
  // closes it. Focus returns to the opener. Escape is handled natively.
  function enhanceDialogs(root) {
    for (const opener of root.querySelectorAll('[data-open-dialog]')) {
      opener.addEventListener('click', () => {
        const dialog = document.getElementById(opener.dataset.openDialog);
        if (!dialog) return;
        if (opener.dataset.dialogContext) {
          const slot = dialog.querySelector('[data-dialog-context]');
          if (slot) slot.textContent = opener.dataset.dialogContext;
        }
        dialog._opener = opener;
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        const first = dialog.querySelector('[autofocus], input, select, textarea, button:not(:disabled)');
        if (first) first.focus();
      });
    }
    for (const dialog of root.querySelectorAll('dialog')) {
      dialog.addEventListener('close', () => {
        if (dialog._opener) dialog._opener.focus();
      });
      for (const closer of dialog.querySelectorAll('[data-close-dialog]')) {
        closer.addEventListener('click', () => {
          if (typeof dialog.close === 'function') dialog.close();
          else { dialog.removeAttribute('open'); if (dialog._opener) dialog._opener.focus(); }
        });
      }
    }
  }

  // ------------------------------------------------------------------- tabs
  // <div data-tabs> containing [role=tablist] > [role=tab][aria-controls]
  // and matching [role=tabpanel] elements.
  function enhanceTabs(root) {
    for (const host of root.querySelectorAll('[data-tabs]')) {
      const tabs = [...host.querySelectorAll('[role="tab"]')];
      const select = tab => {
        for (const t of tabs) {
          const on = t === tab;
          t.setAttribute('aria-selected', String(on));
          t.tabIndex = on ? 0 : -1;
          const panel = document.getElementById(t.getAttribute('aria-controls'));
          if (panel) panel.hidden = !on;
        }
      };
      tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => select(tab));
        tab.addEventListener('keydown', event => {
          let next = null;
          if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
          if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
          if (event.key === 'Home') next = tabs[0];
          if (event.key === 'End') next = tabs[tabs.length - 1];
          if (next) { event.preventDefault(); select(next); next.focus(); }
        });
      });
      const initial = tabs.find(t => t.getAttribute('aria-selected') === 'true') || tabs[0];
      if (initial) select(initial);
    }
  }

  // ------------------------------------------------------------ form checks
  // <form data-preview-form> is checked locally on submit. A valid form is
  // never saved: the status line says so explicitly.
  function enhanceForms(root) {
    for (const form of root.querySelectorAll('form[data-preview-form]')) {
      form.noValidate = true;
      const status = form.querySelector('.form-status') ||
        form.appendChild(el('p', {class: 'form-status', role: 'status'}));
      status.setAttribute('role', 'status');
      form.addEventListener('submit', event => {
        event.preventDefault();
        let firstInvalid = null;
        for (const field of form.querySelectorAll('input, select, textarea')) {
          if (field.disabled || field.type === 'file') continue;
          const holder = field.closest('.form-field');
          const old = holder && holder.querySelector('.field-error');
          if (old) old.remove();
          field.removeAttribute('aria-invalid');
          if (!field.checkValidity()) {
            firstInvalid = firstInvalid || field;
            field.setAttribute('aria-invalid', 'true');
            if (holder) {
              const id = (field.id || 'f' + (++ncCount)) + '-error';
              holder.append(el('span', {class: 'field-error', id, text: field.validationMessage}));
              field.setAttribute('aria-describedby', id);
            }
          }
        }
        if (firstInvalid) {
          status.className = 'form-status notice bad';
          status.textContent = 'Please correct the highlighted fields.';
          firstInvalid.focus();
          return;
        }
        status.className = 'form-status notice info';
        status.textContent = form.dataset.previewForm ||
          'Entries checked in this browser only. Saving is not connected yet — ' +
          'nothing was stored or sent.';
      });
      form.addEventListener('reset', () => {
        status.className = 'form-status';
        status.textContent = '';
        for (const e of form.querySelectorAll('.field-error')) e.remove();
        for (const f of form.querySelectorAll('[aria-invalid]')) f.removeAttribute('aria-invalid');
      });
    }
  }

  // ---------------------------------------------------------------- filters
  // <form class="filters" data-filters="countId"> — no records are connected
  // yet, so filters only report what would be applied.
  function enhanceFilters(root) {
    for (const form of root.querySelectorAll('form[data-filters]')) {
      const out = document.getElementById(form.dataset.filters);
      const update = () => {
        let active = 0;
        for (const field of form.querySelectorAll('input, select')) {
          if (field.type === 'checkbox' ? field.checked : field.value.trim() !== '') active += 1;
        }
        if (out) {
          out.textContent = '0 records shown' +
            (active ? ` · ${active} filter${active === 1 ? '' : 's'} selected` : '') +
            '. No records are available until backend data is connected.';
        }
      };
      form.addEventListener('submit', e => e.preventDefault());
      form.addEventListener('input', update);
      form.addEventListener('change', update);
      form.addEventListener('reset', () => setTimeout(update, 0));
      update();
    }
  }

  // ------------------------------------------------------------ file picker
  // <div data-file-picker> with an <input type=file multiple>, a .file-list
  // and a .file-status. Files are listed and can be removed; they never
  // leave the browser tab.
  const ALLOWED = ['pdf', 'doc', 'docx'];
  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }
  function enhanceFilePickers(root) {
    for (const host of root.querySelectorAll('[data-file-picker]')) {
      const input = host.querySelector('input[type="file"]');
      const list = host.querySelector('.file-list');
      const status = host.querySelector('.file-status');
      const files = [];
      const render = () => {
        list.replaceChildren();
        if (!files.length) {
          list.append(el('li', {class: 'unavailable', text: 'No documents selected.'}));
          return;
        }
        files.forEach((file, index) => {
          const ext = file.name.split('.').pop().toUpperCase();
          list.append(el('li', {},
            el('span', {class: 'file-name', text: file.name}),
            el('span', {class: 'file-meta', text: `${ext} · ${formatSize(file.size)}`}),
            badge('Selected locally — not uploaded', 'warn'),
            el('button', {type: 'button', class: 'btn small',
                          'aria-label': 'Remove ' + file.name, text: 'Remove',
                          onclick: () => {
                            files.splice(index, 1);
                            render();
                            status.textContent = `Removed ${file.name}. ${files.length} document(s) selected.`;
                            input.focus();
                          }})));
        });
      };
      input.addEventListener('change', () => {
        const rejected = [];
        let added = 0;
        for (const file of input.files) {
          const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
          if (!ALLOWED.includes(ext)) { rejected.push(file.name); continue; }
          if (files.some(f => f.name === file.name && f.size === file.size)) continue;
          files.push(file);
          added += 1;
        }
        input.value = '';
        render();
        status.textContent = `${added} document(s) added, ${files.length} selected in total.` +
          (rejected.length ? ` Not accepted (PDF, DOC or DOCX only): ${rejected.join(', ')}.` : '') +
          ' Nothing has been uploaded.';
      });
      render();
    }
  }

  function enhance(root) {
    root = root || document;
    enhanceNotConnected(root);
    enhanceDialogs(root);
    enhanceTabs(root);
    enhanceForms(root);
    enhanceFilters(root);
    enhanceFilePickers(root);
  }

  // ------------------------------------------------------ authorization
  // The server only sends this page after verifying administrative access.
  // The page still asks the server (GET /admin/session, HttpOnly cookie) for
  // the caller's role and effective permissions, removes everything the
  // caller may not use, and only then reveals the interface
  // (body[data-auth="pending"] is hidden by admin.css). The browser never
  // decides access on its own: every later request is checked again by the
  // server, and the permission keys come from the backend registry.
  const SESSION_URL = '/admin/session';
  const ROLE_LABELS = {administrator: 'Administrator', admin_employee: 'Admin Employee'};

  function applyPermissions(root, session) {
    const granted = new Set(session.permissions);
    for (const node of [...root.querySelectorAll('[data-requires]')]) {
      const needed = node.dataset.requires.split(/\s+/).filter(Boolean);
      if (!needed.some(p => granted.has(p))) node.remove();      // unknown keys: removed
    }
    // In-page links to Administrator pages the caller may not open.
    for (const link of [...root.querySelectorAll('#main a[href]')]) {
      const page = link.getAttribute('href').split('#')[0].split('?')[0];
      if (/^[a-z-]+\.html$/.test(page) && session.pages[page] !== true) link.remove();
    }
  }

  function revokeUiSession() {
    return fetch(SESSION_URL, {method: 'DELETE', credentials: 'same-origin', keepalive: true})
      .catch(() => {});
  }

  function showDenied(status) {
    const text = status === 401
      ? 'Your administrator session has ended. Reload the page to sign in again.'
      : status === 403 ? 'Administrator access is not available for this account.'
      : 'Administrator access could not be verified, so the interface is not shown.';
    const app = document.querySelector('.app');
    if (app) {
      app.replaceChildren(el('main', {id: 'main', class: 'content adm-content', tabindex: '-1'},
        el('h1', {text: 'Administrator access'}),
        el('p', {class: 'notice bad', role: 'alert', text}),
        el('p', {}, el('a', {class: 'btn', href: '/dashboard', text: 'Back to Innovator'}))));
    }
    for (const banner of document.querySelectorAll('.preview-banner')) banner.remove();
    document.body.dataset.auth = 'denied';
  }

  function scheduleExpiryNotice(session) {
    const ms = session.expires_at * 1000 - Date.now();
    if (!(ms > 0) || ms > 2147483647) return;
    setTimeout(() => {
      const main = document.getElementById('main');
      if (!main || document.getElementById('sessionExpired')) return;
      main.prepend(el('p', {id: 'sessionExpired', class: 'notice warn', role: 'alert',
        text: 'Your administrator session has expired. Reload the page to continue; access ' +
              'will be checked again.'}));
    }, ms);
  }

  // Page scripts register a builder; it runs after authorization and before
  // the generic enhancement so generated markup is filtered and enhanced too.
  const builders = [];
  function onReady(fn) { builders.push(fn); }

  document.addEventListener('DOMContentLoaded', async () => {
    let response = null;
    let session = null;
    try {
      response = await fetch(SESSION_URL, {credentials: 'same-origin', cache: 'no-store',
                                           headers: {Accept: 'application/json'}});
      if (response.ok) session = await response.json();
    } catch (error) {
      session = null;
    }
    if (!session || !Array.isArray(session.permissions) || !session.pages ||
        !ROLE_LABELS[session.role] || session.account_status !== 'active') {
      showDenied(response ? response.status : 0);
      return;
    }

    window.AdminSession = Object.freeze({...session, roleLabel: ROLE_LABELS[session.role]});
    const label = document.getElementById('adminRoleLabel');
    if (label) label.textContent = ROLE_LABELS[session.role];

    for (const fn of builders) fn(window.AdminSession);
    applyPermissions(document, session);
    enhance(document);

    const logout = document.getElementById('logoutButton');
    if (logout) logout.addEventListener('click', revokeUiSession, {capture: true});
    scheduleExpiryNotice(session);

    document.body.dataset.auth = 'ready';
    const heading = document.querySelector('#main h1');
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      document.title = `${heading.textContent} · Administrator | Profile Match`;
    }
  });

  window.AdminUI = {el, badge, ncButton, emptyRow, enhance, onReady, NOT_CONNECTED, ROLE_LABELS};
})();
