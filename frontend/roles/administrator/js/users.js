// Administrator module — User Management.
// No user records are loaded. Account actions open confirmation dialogs whose
// final confirmation is disabled: nothing is suspended, banned, restored or
// deleted, and no role is assigned or removed.
(function () {
  'use strict';
  const {el, emptyRow, onReady} = window.AdminUI;

  const ROLES = ['Administrator', 'Admin Employee', 'Innovator', 'Innovation Center',
                 'Industry Liaison', 'Management', 'External Partner'];

  const ACTIONS = [
    {id: 'suspend', label: 'Suspend account', danger: false,
     text: 'Suspending temporarily blocks sign-in. The account and its records are kept and can be restored.'},
    {id: 'ban', label: 'Ban account', danger: true,
     text: 'Banning permanently blocks sign-in for this account until an administrator restores it.'},
    {id: 'restore', label: 'Restore account', danger: false,
     text: 'Restoring returns a suspended or banned account to active status.'},
    {id: 'delete', label: 'Delete account', danger: true,
     text: 'Deleting removes the account. This cannot be undone. Records owned by the account must be ' +
           'reviewed before deletion.'}
  ];

  function dialogFor(action) {
    const id = 'dlg-' + action.id;
    const reasonId = id + '-reason';
    return el('dialog', {id, class: 'adm-dialog', 'aria-labelledby': id + '-h',
                         'data-requires': 'users.' + action.id},
      el('div', {class: 'dialog-body'},
        el('h2', {id: id + '-h', text: action.label + '?'}),
        el('p', {text: action.text}),
        el('p', {class: 'notice warn', text: 'No user is selected, and account actions are not connected ' +
                                             'yet. Confirming is disabled.'}),
        el('label', {class: 'form-field', for: reasonId}, 'Reason (recorded in the audit log)',
          el('textarea', {id: reasonId, rows: '3'})),
        action.id === 'delete'
          ? el('label', {class: 'form-field', for: id + '-type', style: 'margin-top:10px'},
              'Type DELETE to confirm',
              el('input', {id: id + '-type', type: 'text', autocomplete: 'off'}))
          : null),
      el('div', {class: 'dialog-actions'},
        el('button', {type: 'button', class: 'btn small', 'data-close-dialog': true, text: 'Cancel'}),
        el('button', {type: 'button', class: 'btn small' + (action.danger ? ' danger' : ''),
                      'data-nc': 'Not connected — no account will be changed.',
                      text: 'Confirm ' + action.label.toLowerCase()})));
  }

  onReady(() => {
    emptyRow(document.getElementById('userRows'), 7, 'No user records',
      'User accounts will be listed here once the administrator backend is connected. ' +
      'No private user data is loaded.');
    emptyRow(document.getElementById('activityRows'), 4, 'No activity history',
      'Sign-ins, role changes and account status changes will appear here for the selected user.');

    document.getElementById('roleChecks').replaceChildren(...ROLES.map((role, i) =>
      el('li', {}, el('label', {class: 'check', for: 'role-' + i},
        el('input', {type: 'checkbox', id: 'role-' + i, value: role}), role))));

    document.getElementById('accountActions').replaceChildren(...ACTIONS.map(action =>
      el('button', {type: 'button', class: 'btn small' + (action.danger ? ' danger' : ''),
                    'data-open-dialog': 'dlg-' + action.id, 'aria-haspopup': 'dialog',
                    'data-requires': 'users.' + action.id,
                    text: action.label + '…'})));
    document.getElementById('accountDialogs').replaceChildren(...ACTIONS.map(dialogFor));
  });
})();
