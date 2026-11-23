// Veronos CRM: interested replies land here automatically from Instantly.
// Instantly > Settings > Integrations > Webhooks > event "Lead interested" > this web app's URL.
// Run setup() once from the editor to build the Pipeline tab.

const TAB = 'Pipeline';
// Flow: interested reply -> ask for a cell -> build homepage -> send by email + text -> live 7 days -> 3 emails to book the meeting.
const HEAD = ['Date replied', 'Status', 'Company', 'Contact', 'Email', 'Cell (for texting)', 'Website', 'City', 'Niche',
  "What's wrong with their site", 'Their reply', 'Preview link', 'Preview sent', 'Preview expires', 'Follow-up 1', 'Follow-up 2', 'Follow-up 3',
  'Meeting booked', 'Plan', 'Notes', 'Office phone (backup)', 'Campaign'];
const STATUSES = ['Asked for cell', 'Building', 'Preview sent', 'Meeting booked', 'Won', 'Lost'];

function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(TAB) || ss.insertSheet(TAB);
  sh.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight('bold').setBackground('#1f3d2b').setFontColor('#ffffff');
  sh.setFrozenRows(1);
  sh.getRange('B2:B').setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES, true).build());
  sh.getRange('N2:N').setFormula('=IF(M2="","",M2+7)');
  sh.getRange('M2:N').setNumberFormat('mmm d');
  const rules = [['Asked for cell', '#fff2cc'], ['Building', '#cfe2f3'], ['Preview sent', '#d9d2e9'], ['Call booked', '#fce5cd'], ['Won', '#d9ead3'], ['Lost', '#efefef']]
    .map(([v, c]) => SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(v).setBackground(c).setRanges([sh.getRange('B2:B')]).build());
  sh.setConditionalFormatRules(rules);
  [100, 120, 180, 120, 200, 130, 220, 110, 140, 240, 300, 200, 100, 100, 90, 90, 90, 110, 80, 220, 130, 130].forEach((w, i) => sh.setColumnWidth(i + 1, w));
  const d = ss.getSheetByName('Sheet1'); if (d && ss.getSheets().length > 1 && d.getLastRow() === 0) ss.deleteSheet(d);
}

// Pull a value out of the webhook body whatever Instantly calls it (top level or nested under lead/payload/variables).
function pick_(o, names) {
  const flat = {};
  (function walk(x) {
    if (!x || typeof x !== 'object') return;
    Object.keys(x).forEach(k => {
      const v = x[k];
      if (v && typeof v === 'object') walk(v);
      else if (v !== null && v !== '' && !(k.toLowerCase() in flat)) flat[k.toLowerCase()] = String(v);
    });
  })(o);
  for (const n of names) { const v = flat[n.toLowerCase()]; if (v) return v; }
  return '';
}

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'not json' }); }
  const email = pick_(body, ['lead_email', 'email', 'lead']).toLowerCase().trim();
  if (!email || email.indexOf('@') < 0) return out_({ ok: false, error: 'no email' });
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(TAB);
  const last = sh.getLastRow();
  if (last > 1 && sh.getRange(2, 5, last - 1, 1).getValues().some(r => String(r[0]).toLowerCase() === email)) return out_({ ok: true, dup: true });
  const reply = pick_(body, ['reply_text_snippet', 'reply_text', 'reply_body', 'body', 'text']).slice(0, 1000);
  const row = [new Date(), 'Asked for cell',
    pick_(body, ['companyName', 'company_name', 'company']),
    pick_(body, ['firstName', 'first_name']),
    email, '',
    pick_(body, ['website', 'company_domain']),
    pick_(body, ['city']),
    pick_(body, ['nicheLine', 'service']),
    pick_(body, ['hook']),
    reply, '', '', '', '', '', '', '', '', '',
    pick_(body, ['phone', 'phone_number']),
    pick_(body, ['campaign_name', 'campaign'])];
  sh.appendRow(row);
  const r = sh.getLastRow(); sh.getRange(r, 14).setFormula('=IF(M' + r + '="","",M' + r + '+7)');
  return out_({ ok: true });
}

function doGet() { return out_({ ok: true, crm: 'veronos' }); }
function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

// Run from the editor to see a fake "yes" land in the sheet.
function testRow() {
  doPost({ postData: { contents: JSON.stringify({ event_type: 'lead_interested', campaign_name: 'Veronos - US', lead_email: 'test@example.com',
    firstName: 'Dr. Test', companyName: 'Test Dental', website: 'https://example.com', city: 'Phoenix', nicheLine: 'dental practices',
    hook: 'is really hard to use on a phone', phone: '(602) 555-0100', reply_text: 'Sure, go ahead and make it' }) } });
}
