// Shared rider-presentation helpers used across the stage chart, riders grid,
// and rider detail page.

/** "Firstname Lastname" when scrape data is present; falls back to PCS "LastName Firstname". */
export function displayName(r: { name: string; firstName?: string; lastName?: string }): string {
  return r.firstName && r.lastName ? `${r.firstName} ${r.lastName}` : r.name;
}

// "Soviet Union" and "Yugoslavia" are genuine historical entities with no
// current ISO 3166-1 code / flag emoji, so they get hand-built inline SVGs
// (official Wikimedia Commons artwork) instead of an emoji lookup — see
// HISTORICAL_FLAG_SVG below. The star/hammer/sickle on the Soviet flag are
// enlarged (1.6x, per request) relative to the official proportions so the
// emblem stays legible at the small size these render at in the app.
const HISTORICAL_FLAG_SVG: Record<string, string> = {
  "Soviet Union": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1.3em" height="0.65em"><path fill="#bc0000" fill-opacity="1" d="M0 0h1200v600H0z" style="fill:#cc0000;fill-opacity:1" /><g transform="translate(209.5,90) scale(1.6) translate(-209.5,-90)"><path d="m 200.0005,37.5 -8.41933,25.911886 H 164.336 L 186.37777,79.426122 177.95844,105.338 200.0005,89.323465 222.04257,105.338 213.62324,79.426122 235.665,63.411886 h -27.24516 z m 0,13.499987 5.38828,16.583473 h 17.43718 l -14.107,10.249496 5.38827,16.583472 L 200.0005,84.167224 185.89378,94.416428 191.28205,77.832956 177.17504,67.58346 h 17.43718 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.14999977px;stroke-linecap:butt;stroke-linejoin:miter;stroke-opacity:1" /><g style="fill:#ffd700;fill-opacity:1" transform="matrix(0.98931879,0,0,0.98673811,3.8297658,3.7659398)"><path d="m 137.43744,171.69421 18.86296,18.9937 17.78834,-17.66589 c 27.05847,29.021 55.43807,56.99501 82.28704,86.12782 4.03444,4.06233 10.59815,4.085 14.66056,0.0506 4.06232,-4.03445 4.08499,-10.59815 0.0506,-14.66056 -28.81871,-27.1901 -57.72545,-54.60143 -86.55328,-81.89095 l 23.96499,-23.80003 -33.34026,-4.61605 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.48919073;stroke-miterlimit:4;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:1" /><path d="m 198.2887,110.1955 c 15.51743,8.7394 27.29872,21.28122 34.2484,34.3924 7.04394,13.28902 10.13959,27.16218 10.20325,38.25433 0.13054,22.74374 -18.43771,41.18184 -41.18183,41.18184 -12.13597,0 -23.04607,-5.24868 -30.58302,-13.60085 l -4.16863,3.51033 c -0.70999,-0.27231 -1.46387,-0.41221 -2.22429,-0.41276 -1.82948,1.9e-4 -3.56621,0.80531 -4.74859,2.20136 -2.97368,0.38896 -5.46251,2.44529 -6.40534,5.29224 -3.13486,6.28843 -8.63524,11.21997 -15.29104,13.4776 -0.0637,0.0216 -0.11992,0.05 -0.1758,0.0783 -3.07749,1.12758 -6.16259,3.1643 -8.78919,5.80245 -5.19155,5.23656 -7.72858,11.93658 -6.30024,16.63822 -0.14098,0.40857 -0.21361,0.83759 -0.21498,1.26979 1.5e-4,2.17082 1.75991,3.93058 3.93073,3.93073 0.54341,-0.002 1.08053,-0.11639 1.57745,-0.33632 4.69369,1.05881 11.06885,-1.54582 16.05444,-6.55917 2.82624,-2.85072 4.94356,-6.22349 5.98303,-9.53062 2.31696,-6.62278 7.29699,-12.01856 13.62281,-15.05312 0.15105,-0.0725 0.27303,-0.14714 0.38218,-0.22358 2.12082,-1.01408 3.67251,-2.92895 4.225,-5.2139 9.70222,11.44481 24.25255,18.75299 40.51876,19.13577 29.83352,0.70205 52.13299,-21.25802 53.16414,-52.83642 0.51894,-15.89259 -5.62993,-36.3847 -19.6412,-53.19089 -10.70835,-12.84441 -26.40987,-23.50795 -44.18699,-28.20777 z" style="fill:#ffd700;fill-opacity:1;stroke:none;stroke-width:0.50003481;stroke-miterlimit:4;stroke-dasharray:none;stroke-dashoffset:0;stroke-opacity:1" /></g></g></svg>',
  Yugoslavia: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 500" width="1.3em" height="0.65em"><path fill="#003893" d="M0 0h1000v500H0z"/><path fill="#fff" d="M0 166.667h1000V500H0z"/><g fill="#de0000"><path d="M0 333.333h1000V500H0z"/><path fill-rule="evenodd" stroke="#fcd115" stroke-width="8.89" d="m500 97.716 34.193 105.222 110.638.005-89.506 65.035 34.185 105.225-89.51-65.03-89.511 65.029 34.185-105.225-89.506-65.035 110.638-.005z"/></g></svg>',
};

// Every current-country nationality string that appears in the exported
// data (checked against all 112 years).
const NATIONALITY_TO_ISO: Record<string, string> = {
  Algeria: "DZ", Argentina: "AR", Australia: "AU", Austria: "AT", Belarus: "BY",
  Belgium: "BE", Brazil: "BR", Canada: "CA", China: "CN", Colombia: "CO",
  "Costa Rica": "CR", Croatia: "HR", "Czech Republic": "CZ", Denmark: "DK",
  Ecuador: "EC", Eritrea: "ER", Estonia: "EE", Ethiopia: "ET", Finland: "FI",
  France: "FR", Germany: "DE", "Great Britain": "GB", Hungary: "HU",
  Ireland: "IE", Israel: "IL", Italy: "IT", Japan: "JP", Kazakhstan: "KZ",
  Latvia: "LV", Liechtenstein: "LI", Lithuania: "LT", Luxembourg: "LU",
  Mexico: "MX", Moldova: "MD", Monaco: "MC", Morocco: "MA", Netherlands: "NL",
  "New Zealand": "NZ", Norway: "NO", Poland: "PL", Portugal: "PT",
  Romania: "RO", Russia: "RU", Slovakia: "SK", Slovenia: "SI",
  "South Africa": "ZA", Spain: "ES", Sweden: "SE", Switzerland: "CH",
  Tunisia: "TN", Ukraine: "UA", "United States": "US", Uzbekistan: "UZ",
  Venezuela: "VE",
};

// Regional Indicator Symbols: each ISO 3166-1 alpha-2 letter maps to a
// Unicode codepoint offset by 127397, so "FR" renders as the French flag
// emoji. No image assets or network requests needed.
export function isoToFlagEmoji(iso2: string): string {
  return [...iso2.toUpperCase()].map((c) => String.fromCodePoint(127397 + c.charCodeAt(0))).join("");
}

/** Small flag <span> for a nationality, or null if unrecognized/absent. */
export function nationalityFlagEl(nationality: string | null | undefined): HTMLSpanElement | null {
  if (!nationality) return null;
  const flag = document.createElement("span");
  flag.className = "nationality-flag";
  flag.title = nationality;
  const historicalSvg = HISTORICAL_FLAG_SVG[nationality];
  if (historicalSvg) {
    flag.innerHTML = historicalSvg;
    return flag;
  }
  const iso2 = NATIONALITY_TO_ISO[nationality];
  if (!iso2) return null;
  flag.textContent = isoToFlagEmoji(iso2);
  return flag;
}
