// Account name and sign-out for role pages (Innovation Center and future roles).
//
// Uses the SAME existing Supabase client (window.getSupabase from api.js) and
// the same calls as the Innovator dashboard: auth.getUser, the user's own
// user_profiles row, and auth.signOut({scope: 'local'}). It changes nothing in
// the existing login, callback, session or logout code, and it loads no
// invention data: role pages show fictional demo data only.
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

    signOut.addEventListener('click', async () => {
      signOut.disabled = true;
      signOut.textContent = 'Signing out...';
      try {
        const client = await window.getSupabase();
        const {error} = await client.auth.signOut({scope: 'local'});
        if (error) throw error;
        window.location.replace('/login');
      } catch (error) {
        console.error('Sign out failed:', error);
        signOut.disabled = false;
        signOut.textContent = 'Sign out';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', start);
})();
