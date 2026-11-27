// Account name and sign-out for role pages (Innovation Center and future roles).
//
// Uses the SAME existing Supabase client (window.getSupabase from api.js) and
// the same calls as the Innovator dashboard: auth.getUser, the user's own
// user_profiles row, and auth.signOut({scope: 'local'}). Before signing out it
// ends the server-side interface sessions (Phase 5.4.3A). It changes nothing in
// the existing login or callback code, and it loads no invention data: role
// pages show fictional demo data only.
(function () {
  'use strict';

  const SUPABASE_LIBRARY = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = () => reject(new Error('Could not load ' + src));
      document.head.append(script);
    });
  }

  // Ends the server-side UI sessions through the shared helper of the
  // interface switcher script (DELETE /admin/session and
  // /institutional/session, bounded wait). Never throws.
  async function endInterfaceSessions() {
    const helper = window.ProfileMatchUISessions;
    if (!helper || typeof helper.end !== 'function') return {confirmed: false};
    try {
      return await helper.end();
    } catch (error) {
      return {confirmed: false};
    }
  }

  async function start() {
    const nameField = document.getElementById('accountName');
    const signOut = document.getElementById('logoutButton');
    if (!nameField || !signOut) return;

    // Opened as a local file (offline UI tests): there is no app session.
    if (location.protocol === 'file:') {
      nameField.textContent = 'Not signed in (offline file)';
      signOut.disabled = true;
      return;
    }

    try {
      if (!window.supabase) await loadScript(SUPABASE_LIBRARY);
      if (!window.getSupabase) await loadScript('/assets/js/api.js');
      const client = await window.getSupabase();
      const {data, error} = await client.auth.getUser();
      if (error || !data.user) { window.location.replace('/login'); return; }

      const {data: profile} = await client.from('user_profiles')
        .select('full_name').eq('id', data.user.id).single();
      nameField.textContent = (profile && profile.full_name) || 'Signed in';
    } catch (error) {
      console.error('Account check failed:', error);
      nameField.textContent = 'Account unavailable';
    }

    let signingOut = false;
    signOut.addEventListener('click', async () => {
      if (signingOut) return;                       // no duplicate sign-out
      signingOut = true;
      signOut.disabled = true;
      signOut.textContent = 'Signing out...';
      // 1. End the server UI sessions (Administrator and institutional) and
      //    wait, with a time limit, for the server to confirm.
      const ended = await endInterfaceSessions();
      try {
        // 2. The existing local Supabase sign-out (unchanged).
        const client = await window.getSupabase();
        const {error} = await client.auth.signOut({scope: 'local'});
        if (error) throw error;
        if (!ended.confirmed) {
          // Signed out on this device, but the server did not confirm that the
          // interface sessions ended; they expire on their own (15 min max).
          nameField.textContent = 'Signed out on this device. The server could not confirm ' +
            'that interface sessions ended; they expire within 15 minutes.';
          console.warn('Interface sessions were not confirmed as ended by the server.');
          await new Promise(resolve => setTimeout(resolve, 2500));
        }
        window.location.replace('/login');
      } catch (error) {
        console.error('Sign out failed:', error);
        signingOut = false;
        signOut.disabled = false;
        signOut.textContent = 'Sign out';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', start);
})();
