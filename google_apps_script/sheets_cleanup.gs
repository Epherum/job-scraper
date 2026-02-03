// sheets_cleanup.gs (standalone)
//
// One Apps Script project. Two types of functions:
// 1) setupJobsSheet + onEdit(e): dropdown validation + decision_at timestamp for the Jobs tab
// 2) purgeJobsTodayNotAFitByTitle + purgeJobsNotAFitByTitle: cleanup utilities
//
// IMPORTANT (standalone script):
// - You must set SHEET_ID
// - You must create an installable trigger for onEdit(e)
//   Triggers → Add Trigger → function "onEdit" → event source "From spreadsheet" → event type "On edit"

const SHEET_ID = '1gtpv560HIrba8uLwqsKmFFuV3N_14RoPQrk_BBcn9lg';

// ===== Decisions =====
const DECISION_TOO_SENIOR = 'OVERSENIOR';

const DECISIONS = [
  'NEW',
  'OVERSENIOR',
  'SAVED',
  'APPLIED',
  'SKIPPED_NOT_A_FIT',
  'REJECTED',
  'ARCHIVED',
];

// ===== Regex patterns =====
// Case-insensitive regex patterns.

const TOO_SENIOR_PATTERNS = [
  '\\bexecutive\\b',
  '\\bdirector\\b',
  '\\bdirecteur\\b',
  '\\bdirectrice\\b',
  '\\bvp\\b',
  '\\bvice\\s+president\\b',
  '\\bhead\\s+of\\b',
  '\\bchief\\b',
  '\\bc\\-level\\b',
  '\\bprincipal\\b',
  '\\bstaff\\b',
  '\\blead\\b',
  '\\bmanager\\b',
  '\\bsenior\\b',
  '\\bsr\\b',
  '\\bconfirmé\\b',
  '\\bconfirmée\\b',
];

const DELETE_TITLE_PATTERNS = [
  // Sales-heavy pipeline roles
  'sales\\s+development\\s+representative',
  'business\\s+development\\s+representative',
  '\\bsdr\\b',
  '\\bbdr\\b',

  // Retail / cashier / service / logistics
  '\\bcaissier\\b',
  '\\bcaisse\\b',
  '\\bcashier\\b',
  '\\blivreur\\b',
  '\\bcoursier\\b',
  '\\bchauffeur\\b',
  '\\bpréparateur\\b',
  '\\bpreparateur\\b',

  // Non-software engineering / electrical
  'électricit',
  'electricit',
  'electri(?:c|que)',
  '\\bcfo\\b',
  '\\bcfa\\b',
  'génie\\s+civil',
  'genie\\s+civil',
  'revit',
  'coffrage',
  'ferraillage',

  // Manufacturing/industrial/quality
  'manufactur',
  'industrialisation',
  'maintenance\\s+industrielle',
  'maintenance',
  'assemblage',
  'contrôleur\\s+qualité',
  'controleur\\s+qualite',

  // QA/testing
  '\\bqa\\b',
  'test(\\b|eur|euse)',
  'fonctionnel(?:le)?',

  // Accounting/HR/marketing/product/video
  'comptab',
  'finance\\b',
  'ressources\\s+humaines',
  '\\brh\\b',
  'marketing\\b',
  'chef\\s+de\\s+produit',
  'product\\s+manager',
  'video\\s+editor',
  'monteur\\s+vid(?:é|e)o',
];

// ===== Jobs tab: dropdown + decision_at =====
// Jobs tab columns (1-indexed):
// A date_added
// B source
// C title
// D company
// E location
// F url
// G labels
// H decision
// I decision_at
// J notes
const JOBS_TAB = 'Jobs';
const JOBS_COL_DECISION = 8;
const JOBS_COL_DECISION_AT = 9;

function setupJobsSheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sheet = ss.getSheetByName(JOBS_TAB);
  if (!sheet) throw new Error(`Missing tab: ${JOBS_TAB}`);

  const rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(DECISIONS, true)
    .setAllowInvalid(false)
    .build();

  sheet.getRange(2, JOBS_COL_DECISION, sheet.getMaxRows() - 1, 1).setDataValidation(rule);
}

// Installable trigger target.
function onEdit(e) {
  if (!e || !e.range) return;

  const range = e.range;
  const sheet = range.getSheet();

  if (sheet.getName() !== JOBS_TAB) return;
  if (range.getRow() < 2) return;

  if (range.getColumn() === JOBS_COL_DECISION) {
    const decision = String(range.getValue() || '').trim();
    const tsCell = sheet.getRange(range.getRow(), JOBS_COL_DECISION_AT);

    if (decision === 'APPLIED') {
      if (!tsCell.getValue()) tsCell.setValue(new Date());
    } else {
      tsCell.clearContent();
    }
  }
}

// ===== Cleanup utilities =====
// Jobs_Today tab columns (1-indexed):
// A source
// B labels
// C title
// D company
// E location
// F date_added
// G url
// H decision
// I notes
const JOBS_TODAY_TAB = 'Jobs_Today';
const JOBS_TODAY_COL_TITLE = 3;
const JOBS_TODAY_COL_DECISION = 8;

function purgeJobsTodayNotAFitByTitle() {
  purgeByTitle_({
    tab: JOBS_TODAY_TAB,
    colTitle: JOBS_TODAY_COL_TITLE,
    colDecision: JOBS_TODAY_COL_DECISION,
  });
}

function purgeJobsNotAFitByTitle() {
  // Jobs tab title+decision columns
  purgeByTitle_({
    tab: JOBS_TAB,
    colTitle: 3,
    colDecision: JOBS_COL_DECISION,
  });
}

function purgeByTitle_(cfg) {
  const dryRun = true; // set false to apply

  const reSenior = new RegExp(TOO_SENIOR_PATTERNS.map(p => `(?:${p})`).join('|'), 'i');
  const reDelete = new RegExp(DELETE_TITLE_PATTERNS.map(p => `(?:${p})`).join('|'), 'i');

  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sh = ss.getSheetByName(cfg.tab);
  if (!sh) throw new Error(`Missing tab: ${cfg.tab}`);

  const lastRow = sh.getLastRow();
  const lastCol = sh.getLastColumn();
  if (lastRow < 2) {
    Logger.log(`${cfg.tab}: no rows to process`);
    return;
  }

  const values = sh.getRange(1, 1, lastRow, lastCol).getValues();

  const toSenior = [];
  const toDelete = [];

  for (let r = 2; r <= lastRow; r++) {
    const title = String(values[r - 1][cfg.colTitle - 1] || '').trim();
    if (!title) continue;

    if (reSenior.test(title)) {
      toSenior.push({ row: r, title });
    } else if (reDelete.test(title)) {
      toDelete.push({ row: r, title });
    }
  }

  Logger.log(`${cfg.tab}: OVERSENIOR matches: ${toSenior.length}`);
  toSenior.slice(0, 30).forEach(m => Logger.log(`[OVERSENIOR] #${m.row}: ${m.title}`));

  Logger.log(`${cfg.tab}: DELETE matches: ${toDelete.length}`);
  toDelete.slice(0, 30).forEach(m => Logger.log(`[DELETE] #${m.row}: ${m.title}`));

  if (dryRun) {
    Logger.log('Dry run ON. Set dryRun=false to apply.');
    return;
  }

  // Mark OVERSENIOR but do not override an existing non-empty decision.
  toSenior.forEach(m => {
    const cell = sh.getRange(m.row, cfg.colDecision);
    const cur = String(cell.getValue() || '').trim();
    if (!cur || cur === 'NEW') cell.setValue(DECISION_TOO_SENIOR);
  });

  // Delete bottom-up
  toDelete.sort((a, b) => b.row - a.row);
  toDelete.forEach(m => sh.deleteRow(m.row));

  Logger.log(`${cfg.tab}: Marked OVERSENIOR=${toSenior.length}, Deleted=${toDelete.length}`);
}
