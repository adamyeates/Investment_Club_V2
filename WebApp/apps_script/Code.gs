/**
 * WSIC sheet -> backend webhook.
 *
 * Tells the Python backend "the sheet just changed" the moment anyone adds,
 * edits or deletes a row, so a new buy/sell shows on the website within seconds
 * instead of waiting for the next 60-second poll.
 *
 * SETUP (one time, done by someone with edit access to the sheet):
 *   1. Open the Google Sheet > Extensions > Apps Script. Paste this whole file in.
 *   2. Project Settings (gear icon) > Script properties > add:
 *        BACKEND_URL     https://YOUR-BACKEND/api/webhook/sheet-changed
 *        WEBHOOK_SECRET  (same value as WEBHOOK_SECRET in the backend's .env)
 *   3. Back in the editor, pick "installTriggers" in the function dropdown and
 *      click Run. Approve the permissions prompt (it needs to call an external URL).
 *   4. Optional: run "testWebhook" and check the Execution log says 200.
 *
 * Note: GOOGLEFINANCE price recalculations do NOT fire these triggers. The
 * backend's 60-second poll is what picks up market price moves.
 */

var WATCHED_TABS = ['2025 Portfolio', 'Transactions'];

function installTriggers() {
  var ss = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var fn = t.getHandlerFunction();
    if (fn === 'onSheetEdit' || fn === 'onSheetChange') ScriptApp.deleteTrigger(t);
  });
  // Cell edits (typing a new ticker, changing a quantity after a sale)
  ScriptApp.newTrigger('onSheetEdit').forSpreadsheet(ss).onEdit().create();
  // Structural changes (inserting/deleting rows, pasting blocks, renaming tabs)
  ScriptApp.newTrigger('onSheetChange').forSpreadsheet(ss).onChange().create();
  Logger.log('Triggers installed.');
}

function onSheetEdit(e) {
  var tab = e && e.range ? e.range.getSheet().getName() : '';
  if (tab && WATCHED_TABS.indexOf(tab) === -1) return; // ignore edits on other tabs
  notifyBackend_('edit', tab);
}

function onSheetChange(e) {
  var type = e && e.changeType ? e.changeType : 'OTHER';
  if (type === 'EDIT') return; // already handled by onSheetEdit
  notifyBackend_(type.toLowerCase(), '');
}

function notifyBackend_(kind, tab) {
  // A burst of edits (e.g. pasting 5 rows) should only ping once every 5 seconds.
  var cache = CacheService.getScriptCache();
  if (cache.get('wsic_recent_ping')) return;
  cache.put('wsic_recent_ping', '1', 5);

  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('BACKEND_URL');
  var secret = props.getProperty('WEBHOOK_SECRET');
  if (!url || !secret) {
    Logger.log('BACKEND_URL / WEBHOOK_SECRET script properties are not set.');
    return;
  }
  try {
    var res = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      headers: { 'X-Webhook-Secret': secret },
      payload: JSON.stringify({ kind: kind, tab: tab, at: new Date().toISOString() }),
      muteHttpExceptions: true
    });
    Logger.log('Backend replied ' + res.getResponseCode());
  } catch (err) {
    // Backend asleep or offline: the website still catches up on its next poll.
    Logger.log('Could not reach backend: ' + err);
  }
}

function testWebhook() {
  CacheService.getScriptCache().remove('wsic_recent_ping');
  notifyBackend_('test', '');
}
