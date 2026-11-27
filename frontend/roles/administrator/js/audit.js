// Administrator module — Audit Logs.
// No audit records are loaded or generated.
(function () {
  'use strict';
  const {el, emptyRow, onReady} = window.AdminUI;

  const CATEGORIES = ['User management', 'Permission changes', 'Account bans and deletion',
                      'Organization changes', 'Document uploads', 'Approval decisions',
                      'Agent executions', 'Scheduled collection', 'System errors'];

  onReady(() => {
    document.getElementById('auditCategories').replaceChildren(...CATEGORIES.map((name, i) =>
      el('li', {}, el('label', {class: 'check', for: 'cat-' + i},
        el('input', {type: 'checkbox', id: 'cat-' + i, value: name}), name))));
    emptyRow(document.getElementById('auditRows'), 7, 'No audit records',
      'Audit records will appear here once the audit log is connected. Records cannot be edited or deleted.');
  });
})();
