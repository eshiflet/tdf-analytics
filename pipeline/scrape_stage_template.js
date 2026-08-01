/*
 * PCS Stage Scraper — inject this into a browser on a PCS stage results page.
 *
 * STREAMLINED WORKFLOW (recommended — one tool call per stage):
 *
 * 0. Start the local save server once per session:
 *      cd pipeline/scrapes && nohup python3 save_server.py > /dev/null 2>&1 &
 *    Verify it's writing to the right place with a test POST (see save_server.py
 *    usage in ai-context.md) before scraping real stages.
 * 1. Navigate to https://www.procyclingstats.com/race/tour-de-france/YEAR/stage-N
 * 2. Run EXTRACT_ALL (below) via javascript_tool. In one shot it:
 *      - parses the results table from the already-loaded DOM
 *      - fetches the -points page (same-origin, shares this navigation's
 *        Cloudflare pass) and parses sprint/KOM points from it
 *      - checks for duplicate bibs within the stage's own rows (catches the
 *        "adjacent-row name-swap" artifact — see below — at scrape time
 *        instead of relying solely on detect_name_swaps.py after the fact)
 *      - POSTs the combined JSON straight to the save server (no copy-paste,
 *        no JSON blob through the conversation/context)
 *    It returns a short JSON status summary (row/rider counts, whether the
 *    points fetch succeeded, and any duplicate-bib warnings) — check this.
 * 3. If pointsFetchOk is false (Cloudflare blocked the same-origin fetch),
 *    navigate to .../stage-N-points and run EXTRACT_POINTS instead (dumps to
 *    a <pre> tag), then merge sprint_points/kom_points into the saved
 *    stage_N.json by hand.
 * 4. If dupWarnings is non-empty, treat it as a same-stage swap: cross-check
 *    against adjacent stages (bib should map to the same rider/team
 *    everywhere) before deciding which identity is correct, per the
 *    "Adjacent-row name-swap artifact" section of ai-context.md. NOTE:
 *    dupWarnings only catches the same bib appearing twice in one stage's
 *    own rows — it CANNOT catch a bib appearing once but with the wrong
 *    rider attached (the far more common case, confirmed live 2026-07-25:
 *    re-scraping stage 19 to test this script reproduced the exact
 *    Hindley/Martinez + 3 other swaps fixed earlier that session, with
 *    dupWarnings empty every time). Step 6's cross-stage gate is the real
 *    check — never skip it because a single stage looked clean here.
 * 5. Repeat for each stage.
 * 6. Run: python3 add_stages.py <stage_nums...>  (this also runs the
 *    bib-consistency gate from detect_name_swaps.py before touching the DB —
 *    this is the check that actually catches most swaps; step 2's
 *    dupWarnings is a same-stage-only supplement, not a replacement.)
 *
 * The output format matches what add_stages.py expects.
 *
 * Manual fallback (no save server, or single-page work): EXTRACT_RESULTS and
 * EXTRACT_POINTS below are the original two-page, dump-to-<pre> functions —
 * still here for when the save server isn't running or a single page needs
 * re-extracting in isolation.
 */

// ─── Recommended: one shot per stage, results + points + save ──────────────

const EXTRACT_ALL = `
(async () => {
  function dedupe(s) {
    s = s.replace(/^[,*]+/, '');
    if (s.length > 0 && s.length % 2 === 0 && s.substring(0, s.length/2) === s.substring(s.length/2))
      return s.substring(0, s.length/2);
    return s;
  }
  // PCS renders a rider tied with the row above as a ditto mark (",," in
  // the visible text) but embeds the real, unambiguous value right next to
  // it in a hidden <span class="hide">...</span> — read that authoritative
  // value directly when present instead of relying on textContent
  // concatenation + dedupe() to reverse-engineer it (works today because the
  // hidden value sits immediately after the ditto with nothing separating
  // them, but that's incidental, not guaranteed).
  function readCellText(td) {
    const hide = td.querySelector('span.hide');
    if (hide && hide.textContent.trim()) return hide.textContent.trim();
    return dedupe(td.textContent.trim());
  }

  // ---- 1. Parse main results table ----
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

  const profileIcon = document.querySelector('.icon.profile');
  let profileClass = 'p1';
  if (profileIcon) profileIcon.classList.forEach(c => { if (c.startsWith('p')) profileClass = c; });

  const urlMatch = location.pathname.match(/stage-(\\d+)/);
  const stageNum = urlMatch ? parseInt(urlMatch[1]) : 0;

  const tables = document.querySelectorAll('table');
  let mainTable = tables[0];
  for (const t of tables) {
    const ths = Array.from(t.querySelectorAll('th')).map(h => h.textContent.trim());
    const rowCount = t.querySelectorAll('tbody tr').length;
    if (rowCount > 100 && (ths.includes('Rnk') && (ths.includes('GC') || ths.includes('BIB')))) {
      mainTable = t;
      break;
    }
  }

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
      gcLag = readCellText(tds[2]);
      colOffset = 0;
    } else {
      colOffset = -2;
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
    const pnt = tds.length > (11 + colOffset) ? tds[10 + colOffset].textContent.trim() : '';

    const timeTd = tds[tds.length - 1];
    const timeRaw = readCellText(timeTd);

    const absTime = rnk === '1' ? timeRaw : '';
    const gapTime = rnk === '1' ? '' : timeRaw;

    result.push([rnk, gcPos, gcLag, bib, age, riderName, riderSlug, nat,
                 teamName, teamSlug, uci, pnt, '', absTime, gapTime]);
  });

  // ---- 2. Self-check: duplicate bib within this stage's own rows ----
  // Catches the adjacent-row name-swap artifact (or a mis-extracted bib
  // number) the moment it happens, rather than waiting for a later
  // cross-stage majority check to notice.
  const bibSeen = {};
  const dupWarnings = [];
  result.forEach(r => {
    const bib = r[3];
    if (!bib || !/^\\d+$/.test(bib)) return;
    if (bibSeen[bib] !== undefined && bibSeen[bib] !== r[6]) {
      dupWarnings.push('bib ' + bib + ': ' + bibSeen[bib] + ' vs ' + r[6]);
    }
    bibSeen[bib] = r[6];
  });

  // ---- 3. Fetch the points page and parse sprint/KOM points ----
  let sprintPoints = {}, komPoints = {}, pointsFetchOk = false;
  try {
    const pointsUrl = location.pathname.replace(/\\/stage-(\\d+)$/, '/stage-$1-points');
    const resp = await fetch(pointsUrl);
    const html = await resp.text();
    if (!html.includes('Just a moment') && html.length > 5000) {
      const doc = new DOMParser().parseFromString(html, 'text/html');
      doc.querySelectorAll('h4').forEach(h4 => {
        const text = h4.textContent.trim();
        const table = h4.nextElementSibling;
        if (!table || table.tagName !== 'TABLE') return;

        const lower = text.toLowerCase();
        const isKom = lower.startsWith('kom') || lower.startsWith('gpm');
        const isSprint = lower.startsWith('sprint') || lower === 'points at finish';
        if (!isSprint && !isKom) return;

        const ths = table.querySelectorAll('th');
        let pntIdx = -1;
        ths.forEach((th, i) => { if (th.textContent.trim() === 'Pnt') pntIdx = i; });

        table.querySelectorAll('tbody tr').forEach(tr => {
          const tds = tr.querySelectorAll('td');
          if (tds.length < 2 || pntIdx < 0) return;
          const riderA = tr.querySelector('a[href*="rider/"]');
          const slug = riderA ? new URL(riderA.href, location.origin).pathname.replace(/^\\//, '') : '';
          const pts = parseInt(tds[pntIdx].textContent.trim()) || 0;
          if (slug && pts > 0) {
            const target = isKom ? komPoints : sprintPoints;
            target[slug] = (target[slug] || 0) + pts;
          }
        });
      });
      pointsFetchOk = true;
    }
  } catch (e) {
    // leave sprintPoints/komPoints empty — caller falls back to EXTRACT_POINTS
    // on the points page directly (step 3 in the workflow above)
  }

  // ---- 4. POST combined payload to the local save server ----
  const payload = {
    n: stageNum, info: info, rows: result, profile_icon: profileClass,
    sprint_points: sprintPoints, kom_points: komPoints
  };
  let saveMsg = '';
  try {
    const saveResp = await fetch('http://localhost:8765', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    saveMsg = await saveResp.text();
  } catch (e) {
    saveMsg = 'SAVE SERVER UNREACHABLE — start pipeline/scrapes/save_server.py first';
  }

  return JSON.stringify({
    stage: stageNum,
    saveMsg: saveMsg,
    rows: result.length,
    sprintRiders: Object.keys(sprintPoints).length,
    komRiders: Object.keys(komPoints).length,
    pointsFetchOk: pointsFetchOk,
    dupWarnings: dupWarnings
  });
})()
`;

// ─── Manual fallback — STEP 1: run on .../stage-N results page ─────────────

const EXTRACT_RESULTS = `
(() => {
  function dedupe(s) {
    s = s.replace(/^[,*]+/, '');
    if (s.length > 0 && s.length % 2 === 0 && s.substring(0, s.length/2) === s.substring(s.length/2))
      return s.substring(0, s.length/2);
    return s;
  }
  // PCS renders a rider tied with the row above as a ditto mark (",," in
  // the visible text) but embeds the real, unambiguous value right next to
  // it in a hidden <span class="hide">...</span> — read that authoritative
  // value directly when present instead of relying on textContent
  // concatenation + dedupe() to reverse-engineer it (works today because the
  // hidden value sits immediately after the ditto with nothing separating
  // them, but that's incidental, not guaranteed).
  function readCellText(td) {
    const hide = td.querySelector('span.hide');
    if (hide && hide.textContent.trim()) return hide.textContent.trim();
    return dedupe(td.textContent.trim());
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
      gcLag = readCellText(tds[2]);
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
    const timeRaw = readCellText(timeTd);

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

// ─── Manual fallback — STEP 2: run on .../stage-N-points page ──────────────

const EXTRACT_POINTS = `
(() => {
  const h4s = document.querySelectorAll('h4');
  const sprintPoints = {};
  const komPoints = {};

  h4s.forEach(h4 => {
    const text = h4.textContent.trim();
    const table = h4.nextElementSibling;
    if (!table || table.tagName !== 'TABLE') return;

    const lower = text.toLowerCase();
    const isKom = lower.startsWith('kom') || lower.startsWith('gpm');
    const isSprint = lower.startsWith('sprint') || lower === 'points at finish';
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
