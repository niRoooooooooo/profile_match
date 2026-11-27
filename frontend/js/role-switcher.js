// Authorized interface switcher (Phase 5.4.2).
//
// The ONLY source of the interface list is the server: GET /api/access/me,
// called with the page's existing Supabase session. Nothing here grants or
// decides access; every interface re-checks the caller on the server. There
// is no built-in role list, no token or role is stored in the browser, and the
// switcher changes the interface you are looking at, never your assigned role.
//
// - Hidden while the check is pending, when it fails, and when the account
//   has fewer than two available interfaces (ordinary Innovators never see it).
// - Only interfaces the server marks available are listed; nothing is shown
//   disabled or "coming soon".
// - A response is used only if it belongs to the account that is signed in
//   when it arrives (account switching cannot show another account's list).
// - Administrator and institutional interfaces need a short-lived server UI
//   session, started from the existing Supabase session before navigating.
// - On institutional pages the UI session is re-checked periodically, at its
//   expiry, when the tab becomes visible or is restored from history, and
//   when the account changes. When it expires, is revoked, belongs to another
//   account, cannot be verified, or this page's permissions were reduced, the
//   page content is removed. It is never restored without a fresh page load
//   (which the server authorizes again).
// - Server UI sessions must belong to the account signed in to Supabase in
//   this browser; any other account's session is ended.
// - window.ProfileMatchUISessions.end() ends both UI sessions and waits (with
//   a time limit) for the server to confirm. The existing sign-out handlers
//   call it before the Supabase sign-out.
(function () {
  'use strict';

  // The only server endpoints this script may call.
  const ACCESS_URL = '/api/access/me';
  const ADMIN_SESSION_URL = '/admin/session';
  const INSTITUTIONAL_SESSION_URL = '/institutional/session';

  // Interfaces that need a server UI session before they can be opened.
  const UI_SESSION_FOR = {administrator: ADMIN_SESSION_URL, innovation_center: INSTITUTIONAL_SESSION_URL};
  // <body data-role> of the current page -> interface id.
  const PAGE_INTERFACE = {innovator: 'innovator', administrator: 'administrator',
                          'innovation-center': 'innovation_center'};
  const INSTITUTIONAL_PAGES = new Set(['innovation-center']);
  const CHECK_EVERY_MS = 60 * 1000;
  const END_TIMEOUT_MS = 4000;
  const ID_PATTERN = /^[a-z_]+$/;
  const ENDED_EVENT = 'profile-match:ui-session-ended';

  const offline = () => location.protocol === 'file:';

  function request(url, options) {
    return fetch(url, Object.assign({credentials: 'same-origin', cache: 'no-store'}, options));
  }

  const announceEnded = () => document.dispatchEvent(new CustomEvent(ENDED_EVENT));

  // DELETE one UI session; true only if the server confirmed it (2xx).
  async function endOne(url, timeoutMs) {
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const response = await request(url, {method: 'DELETE', keepalive: true,
                                           signal: controller ? controller.signal : undefined});
      return response.ok;
    } catch (error) {
      return false;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  // Ends the administrative and institutional UI sessions and waits (bounded)
  // for the server. {confirmed: true} only when the server confirmed both.
  let ending = null;
  let lastEnded = null;                  // {time, confirmed} of the latest end
  const recentlyEnded = () => Boolean(lastEnded && lastEnded.confirmed &&
                                      Date.now() - lastEnded.time < 10000);
  function endUiSessions(options) {
    if (offline()) return Promise.resolve({confirmed: false, offline: true});
    if (ending) return ending;                     // no duplicate requests
    const timeoutMs = (options && options.timeoutMs) || END_TIMEOUT_MS;
    ending = Promise.all([ADMIN_SESSION_URL, INSTITUTIONAL_SESSION_URL]
      .map(url => endOne(url, timeoutMs)))
      .then(results => {
        lastEnded = {time: Date.now(), confirmed: results.every(Boolean)};
        return {confirmed: lastEnded.confirmed, admin: results[0], institutional: results[1]};
      })
      .finally(() => { announceEnded(); setTimeout(() => { ending = null; }, 0); });
    return ending;
  }
  const revokeUiSessions = () => endUiSessions();

  // Server UI sessions must belong to the Supabase account signed in here.
  // A session of any other account (or with no signed-in account) is ended.
  async function verifySessionOwners(userId) {
    if (offline()) return;
    for (const url of [ADMIN_SESSION_URL, INSTITUTIONAL_SESSION_URL]) {
      try {
        const response = await request(url, {headers: {Accept: 'application/json'}});
        if (!response.ok) continue;                 // no live session here
        const body = await response.json().catch(() => null);
        if (!userId || !body || body.user_id !== userId) {
          await endOne(url, END_TIMEOUT_MS);
          announceEnded();
        }
      } catch (error) {
        /* unreachable: the server refuses the session on its own */
      }
    }
  }

  // The page's existing Supabase client (loaded by the page itself). Never
  // signs in or out; only reads the current session.
  async function existingClient() {
    for (let i = 0; i < 80 && typeof window.getSupabase !== 'function'; i += 1) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (typeof window.getSupabase !== 'function') return null;
    try { return await window.getSupabase(); } catch (error) { return null; }
  }

  async function currentSession() {
    const client = await existingClient();
    if (!client) return null;
    try {
      const {data} = await client.auth.getSession();
      const session = data && data.session;
      return session && session.access_token && session.user && session.user.id
        ? {token: session.access_token, userId: session.user.id} : null;
    } catch (error) {
      return null;
    }
  }

  // {userId, interfaces} from the server, or null (fail closed).
  async function loadInterfaces() {
    const session = await currentSession();
    if (!session) return null;
    try {
      const response = await request(ACCESS_URL, {headers: {
        Authorization: 'Bearer ' + session.token, Accept: 'application/json'}});
      if (response.status === 401 || response.status === 403) {
        revokeUiSessions();
        return null;
      }
      if (!response.ok) return null;
      const body = await response.json();
      if (!body || body.user_id !== session.userId || body.account_status !== 'active' ||
          !Array.isArray(body.interfaces)) return null;
      const interfaces = body.interfaces.filter(item => item && item.available === true &&
        typeof item.id === 'string' && ID_PATTERN.test(item.id) &&
        typeof item.label === 'string' && item.label &&
        typeof item.href === 'string' && item.href.startsWith('/') && !item.href.startsWith('//'));
      return {userId: session.userId, interfaces};
    } catch (error) {
      return null;
    }
  }

  // ------------------------------------------------ institutional page lock

  const LOCK_TEXT = {
    expired: ['Session ended', 'Your institutional session has expired or has ended. ' +
              'Reload the page to sign in again.'],
    denied: ['Access not available', 'Institutional access is not available for this account.'],
    unavailable: ['Access could not be verified', 'Institutional access could not be verified, ' +
                  'so this page has been closed. Try again later.'],
    changed: ['Access changed', 'Your permissions for this interface have changed. ' +
              'Reload the page to continue with your current access.']
  };

  let locked = false;
  function lockInstitutionalPage(kind) {
    if (locked || !INSTITUTIONAL_PAGES.has(document.body.dataset.role) || offline()) return;
    locked = true;
    // Remove protected content, navigation and controls (pending interactions
    // go with them); nothing is restored without a fresh authorized page load.
    for (const node of document.querySelectorAll('body > .app, body > .dev-banner')) node.remove();
    const switcher = document.getElementById('roleSwitcher');
    if (switcher) { switcher.hidden = true; switcher.replaceChildren(); }
    const [title, text] = LOCK_TEXT[kind] || LOCK_TEXT.denied;
    const box = document.createElement('main');
    box.id = 'interfaceLocked';
    box.className = 'content';
    box.tabIndex = -1;
    const heading = document.createElement('h1');
    heading.textContent = title;
    const message = document.createElement('p');
    message.setAttribute('role', 'alert');
    message.textContent = text;
    const links = document.createElement('p');
    for (const [href, label] of [['/dashboard', 'Back to Innovator'], ['/login', 'Sign in']]) {
      const link = document.createElement('a');
      link.className = 'btn';
      link.href = href;
      link.textContent = label;
      links.append(link, ' ');
    }
    box.append(heading, message, links);
    document.body.append(box);
    box.focus();
  }

  function watchInstitutionalSession() {
    const role = document.body.dataset.role;
    if (!INSTITUTIONAL_PAGES.has(role) || offline()) return;
    // What the server granted when it served this page (data-interface-*).
    const pageFile = location.pathname.split('/').pop();
    const servedPermissions = (document.body.dataset.interfacePermissions || '')
      .split(' ').filter(Boolean);
    let sessionUser = null;
    let timer = null;
    let sequence = 0;
    const lock = kind => { clearTimeout(timer); lockInstitutionalPage(kind); };
    const schedule = (expiresAt) => {
      clearTimeout(timer);
      const untilExpiry = Number(expiresAt) * 1000 - Date.now() + 1000;
      const delay = Number.isFinite(untilExpiry) ? Math.min(CHECK_EVERY_MS, untilExpiry)
        : CHECK_EVERY_MS;
      timer = setTimeout(check, Math.max(1000, delay));
    };
    async function check() {
      if (locked) return;
      const mine = ++sequence;
      try {
        const response = await request(INSTITUTIONAL_SESSION_URL,
                                       {headers: {Accept: 'application/json'}});
        if (locked) return;
        if (response.status === 401) { lock('expired'); return; }
        if (response.status === 403) { lock('denied'); return; }
        if (!response.ok) { lock('unavailable'); return; }
        const body = await response.json();
        if (locked) return;
        const actor = body && body.actors && body.actors[PAGE_INTERFACE[role]];
        if (!actor || typeof body.user_id !== 'string') { lock('denied'); return; }
        if (sessionUser && body.user_id !== sessionUser) { lock('expired'); return; }
        sessionUser = sessionUser || body.user_id;
        const granted = new Set(Array.isArray(actor.permissions) ? actor.permissions : []);
        if ((actor.pages && pageFile in actor.pages && actor.pages[pageFile] !== true) ||
            servedPermissions.some(permission => !granted.has(permission))) {
          lock('changed');                         // reduced since the page was served
          return;
        }
        if (mine === sequence) schedule(body.expires_at);   // a newer check reschedules
      } catch (error) {
        lock('unavailable');
      }
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
    window.addEventListener('pageshow', event => { if (event.persisted) check(); });
    document.addEventListener(ENDED_EVENT, check);
    check();
  }

  // ------------------------------------------------------------ switcher

  function build(host) {
    const currentId = PAGE_INTERFACE[document.body.dataset.role] || null;
    const menuId = 'role-switcher-menu';
    let generation = 0;
    let knownUser = null;

    const hide = () => {
      host.hidden = true;
      host.classList.remove('role-switcher');
      host.replaceChildren();
    };

    async function startUiSession(event, link, sessionUrl) {
      event.preventDefault();
      const status = host.querySelector('[role="status"]');
      const say = text => { if (status) { status.hidden = false; status.textContent = text; } };
      say('Checking access...');
      try {
        const session = await currentSession();
        const response = session
          ? await request(sessionUrl, {method: 'POST',
                                       headers: {Authorization: 'Bearer ' + session.token}})
          : null;
        if (response && response.ok) { window.location.assign(link.href); return; }
        say(response && response.status === 403
          ? 'This interface is not available for this account.'
          : 'This interface could not be opened. Please sign in again.');
      } catch (error) {
        say('Access could not be checked. Please try again later.');
      }
    }

    function show(interfaces) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'role-switcher-button';
      button.setAttribute('aria-expanded', 'false');
      button.setAttribute('aria-controls', menuId);
      const small = document.createElement('span');
      small.className = 'role-switcher-kicker';
      small.textContent = 'Switch interface';
      const name = document.createElement('span');
      name.className = 'role-switcher-current';
      name.textContent = interfaces.find(item => item.id === currentId).label;
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
      const status = document.createElement('p');
      status.className = 'role-switcher-note';
      status.setAttribute('role', 'status');
      status.hidden = true;
      const note = document.createElement('p');
      note.className = 'role-switcher-note';
      note.textContent = 'Only interfaces assigned to your account are listed. Switching ' +
        'changes the interface, not your role; each interface is checked by the server.';
      panel.append(list, status, note);

      for (const item of interfaces) {
        const entry = document.createElement('li');
        const link = document.createElement('a');
        link.href = item.href;
        link.dataset.interfaceId = item.id;
        link.textContent = item.label;
        if (item.id === currentId) {
          link.setAttribute('aria-current', 'page');
          const tag = document.createElement('span');
          tag.className = 'role-tag current';
          tag.textContent = 'Current';
          link.append(' ', tag);
        } else if (UI_SESSION_FOR[item.id]) {
          link.addEventListener('click', event => startUiSession(event, link, UI_SESSION_FOR[item.id]));
        }
        entry.append(link);
        list.append(entry);
      }

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
      panel.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); close(true); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          const links = [...list.querySelectorAll('a')];
          const index = links.indexOf(document.activeElement);
          const next = event.key === 'ArrowDown' ? (index + 1) % links.length
            : (index - 1 + links.length) % links.length;
          event.preventDefault();
          links[next].focus();
        }
      });
      button.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); close(true); }
      });
      host.closeMenu = close;

      host.classList.add('role-switcher');
      host.replaceChildren(button, panel);
      host.hidden = false;
    }

    async function refresh(initial) {
      const mine = ++generation;
      if (initial) hide();                                   // nothing shown while pending
      const result = await loadInterfaces();
      if (mine !== generation) return;                       // a newer check is running
      const client = await existingClient();
      const now = await currentSession();
      if (mine !== generation) return;
      // Server UI sessions of another (or no) account are ended.
      if (client) verifySessionOwners(now ? now.userId : null);
      if (!result || !now || now.userId !== result.userId) { hide(); return; }
      knownUser = result.userId;
      const current = result.interfaces.some(item => item.id === currentId);
      if (currentId && !current) {
        // This page's interface is not (or no longer) authorized.
        if (UI_SESSION_FOR[currentId]) revokeUiSessions();
        lockInstitutionalPage('denied');
        hide();
        return;
      }
      // Never shown on a page locked by an account check (dashboard.js).
      if (result.interfaces.length < 2 || locked ||
          document.body.dataset.accountLocked === 'true') { hide(); return; }
      show(result.interfaces);
    }

    document.addEventListener('click', event => {
      if (typeof host.closeMenu === 'function' && !host.contains(event.target)) {
        const panel = host.querySelector('.role-switcher-panel');
        if (panel && !panel.hidden) host.closeMenu(false);
      }
    });

    hide();
    if (offline()) return;                // no server: no interfaces
    refresh(true);
    // Re-check when the tab returns or the page is restored from history
    // (another tab may have signed out or switched account meanwhile).
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(false); });
    window.addEventListener('pageshow', event => { if (event.persisted) refresh(false); });

    // Account changes: discard pending results and re-check for the new account.
    existingClient().then(client => {
      if (!client || !client.auth || typeof client.auth.onAuthStateChange !== 'function') return;
      client.auth.onAuthStateChange((event, session) => {
        const userId = session && session.user ? session.user.id : null;
        if (event === 'SIGNED_OUT' || !userId) {
          generation += 1;
          knownUser = null;
          hide();
          // Also covers sign-out in another tab. Skipped right after an
          // explicit, server-confirmed sign-out in this tab.
          if (!recentlyEnded()) revokeUiSessions();
          lockInstitutionalPage('expired');
          return;
        }
        if (knownUser !== null && userId !== knownUser) {
          generation += 1;
          knownUser = null;
          hide();
          revokeUiSessions();
          lockInstitutionalPage('expired');
          setTimeout(() => refresh(true), 0);   // outside the auth callback
        }
      });
    });
  }

  // Used by the existing sign-out handlers (dashboard.js, session-header.js).
  window.ProfileMatchUISessions = Object.freeze({end: endUiSessions});

  document.addEventListener('DOMContentLoaded', () => {
    const host = document.getElementById('roleSwitcher');
    if (host) build(host);
    watchInstitutionalSession();
  });
})();
