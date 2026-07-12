/*
 * PCS Stage Scraper — inject this into a browser on a PCS stage results page.
 *
 * WORKFLOW (for Claude Code or manual use):
 *
 * 1. Navigate to https://www.procyclingstats.com/race/tour-de-france/YEAR/stage-N
 * 2. Run EXTRACT_RESULTS (below) via javascript_tool — it dumps JSON into a <pre>
 * 3. Read the page text (get_page_text) and save as pipeline/scrapes/stage_N.json
 * 4. Navigate to .../stage-N-points
 * 5. Run EXTRACT_POINTS — it dumps sprint + KOM points JSON into a <pre>
 * 6. Read page text, parse the JSON, and merge sprint_points + kom_points into
 *    the stage_N.json saved in step 3
 * 7. Repeat for each stage
 * 8. Run: python3 add_stages.py <stage_nums...>
 *
 * The output format matches what add_stages.py expects.
 */

// ─── STEP 1: Run on .../stage-N results page ───────────────────────────────

const EXTRACT_RESULTS = `
(() => {
  function dedupe(s) {
    s = s.replace(/^[,*]+/, '');
    if (s.length > 0 && s.length % 2 === 0 && s.substring(0, s.length/2) === s.substring(s.length/2))
      return s.substring(0, s.length/2);
    return s;
  }

  // Stage info from page text
  const bodyText = document.body.innerText;
  const fields = ['Won how', 'Vertical meters', 'ProfileScore', 'Distance',
                  'Departure', 'Arrival', 'Date', 'Start time', 'Avg. speed winner',
                  'Classification', 'Race category', 'Points scale', 'UCI scale',
                  'Gradient final km', 'Timelimit', 'Avg. temperature'];
  const info = {};
  fields.forEach(f => {
    const idx = bodyText.indexOf(f + ':');
    if (idx >= 0) {
      const after = bodyText.substring(idx + f.length + 1, idx + f.length + 80);
      info[f] = after.split('\\n')[1]?.trim() || after.split('\\n')[0]?.trim() || '';
    }
  });

  // Profile icon
  const profileIcon = document.querySelector('.icon.profile');
  let profileClass = 'p1';
  if (profileIcon) profileIcon.classList.forEach(c => { if (c.startsWith('p')) profileClass = c; });

  // Stage number from URL
  const urlMatch = location.pathname.match(/stage-(\\d+)/);
  const stageNum = urlMatch ? parseInt(urlMatch[1]) : 0;

  // Find main results table (has Rnk | GC | Timelag columns, or Rnk | BIB for TTT)
  const tables = document.querySelectorAll('table');
  let mainTable = tables[0]; // fallback
  for (const t of tables) {
    const ths = Array.from(t.querySelectorAll('th')).map(h => h.textContent.trim());
    const rowCount = t.querySelectorAll('tbody tr').length;
    if (rowCount > 100 && (ths.includes('Rnk') && (ths.includes('GC') || ths.includes('BIB')))) {
      mainTable = t;
      break;
    }
  }

  // Check if GC column exists (not present in TTT stage 1)
  const mainThs = Array.from(mainTable.querySelectorAll('th')).map(h => h.textContent.trim());
  const hasGC = mainThs.includes('GC');

  const rows = mainTable.querySelectorAll('tbody tr');
  const result = [];

  rows.forEach(tr => {
    const tds = tr.querySelectorAll('td');
    if (tds.length < 8) return;

    let colOffset = 0;
    const rnk = tds[0].textContent.trim();

    let gcPos = '', gcLag = '';
    if (hasGC) {
      gcPos = tds[1].textContent.trim();
      gcLag = dedupe(tds[2].textContent.trim());
      colOffset = 0;
    } else {
      colOffset = -2; // no GC/Timelag columns
    }

    const bib = tds[3 + colOffset].textContent.trim();
    const age = tds[6 + colOffset].textContent.trim();

    const riderTd = tds[7 + colOffset];
    const riderA = riderTd.querySelector('a');
    const riderName = riderA ? riderA.textContent.trim() : '';
    const riderSlug = riderA ? new URL(riderA.href).pathname.replace(/^\\//, '') : '';
    const flagSpan = riderTd.querySelector('span.flag');
    let nat = '';
    if (flagSpan) flagSpan.classList.forEach(c => { if (c !== 'flag') nat = c; });

    const teamTd = tds[8 + colOffset];
    const teamA = teamTd.querySelector('a');
    const teamName = teamA ? teamA.textContent.trim() : '';
    const teamSlug = teamA ? new URL(teamA.href).pathname.replace(/^\\//, '') : '';

    const uci = tds[9 + colOffset].textContent.trim();
    // Pnt column may or may not exist depending on table structure
    const pnt = tds.length > (11 + colOffset) ? tds[10 + colOffset].textContent.trim() : '';

    const timeTd = tds[tds.length - 1];
    const timeRaw = dedupe(timeTd.textContent.trim());

    const absTime = rnk === '1' ? timeRaw : '';
    const gapTime = rnk === '1' ? '' : timeRaw;

    result.push([rnk, gcPos, gcLag, bib, age, riderName, riderSlug, nat,
                 teamName, teamSlug, uci, pnt, '', absTime, gapTime]);
  });

  const output = JSON.stringify({
    n: stageNum,
    info: info,
    rows: result,
    profile_icon: profileClass,
    sprint_points: {},
    kom_points: {}
  });

  const pre = document.createElement('pre');
  pre.textContent = output;
  document.body.innerHTML = '';
  document.body.appendChild(pre);
  return result.length + ' rows extracted for stage ' + stageNum;
})()
`;

// ─── STEP 2: Run on .../stage-N-points page ─────────────────────────────────

const EXTRACT_POINTS = `
(() => {
  const h4s = document.querySelectorAll('h4');
  const sprintPoints = {};
  const komPoints = {};

  h4s.forEach(h4 => {
    const text = h4.textContent.trim();
    const table = h4.nextElementSibling;
    if (!table || table.tagName !== 'TABLE') return;

    const isKom = text.toLowerCase().startsWith('kom');
    const isSprint = text.toLowerCase().startsWith('sprint') || text.toLowerCase() === 'points at finish';
    if (!isSprint && !isKom) return;

    const ths = table.querySelectorAll('th');
    let pntIdx = -1;
    ths.forEach((th, i) => { if (th.textContent.trim() === 'Pnt') pntIdx = i; });

    table.querySelectorAll('tbody tr').forEach(tr => {
      const tds = tr.querySelectorAll('td');
      if (tds.length < 2 || pntIdx < 0) return;
      const riderA = tr.querySelector('a[href*="rider/"]');
      const slug = riderA ? new URL(riderA.href).pathname.replace(/^\\//, '') : '';
      const pts = parseInt(tds[pntIdx].textContent.trim()) || 0;
      if (slug && pts > 0) {
        const target = isKom ? komPoints : sprintPoints;
        target[slug] = (target[slug] || 0) + pts;
      }
    });
  });

  const output = JSON.stringify({ sprint_points: sprintPoints, kom_points: komPoints });
  const pre = document.createElement('pre');
  pre.textContent = output;
  document.body.innerHTML = '';
  document.body.appendChild(pre);
  return 'sprint: ' + Object.keys(sprintPoints).length + ' riders, kom: ' + Object.keys(komPoints).length + ' riders';
})()
`;
