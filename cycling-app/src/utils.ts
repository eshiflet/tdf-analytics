// Generic helpers with no dependency on app state or DOM structure.

export function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

/** Escape text for interpolation into an innerHTML template. Every tooltip is
 *  built that way, and the strings in it (rider, team, place and race names)
 *  come from scraped data, so none of them may be trusted to be markup-free.
 *  Also stops a bare "&" in a team name from being parsed as an entity. */
export function escapeHtml(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!
  ));
}

/** "Only the latest call may apply its result." begin() hands out a token;
 *  isCurrent(token) is false once a later begin() has happened. For async work
 *  whose responses can arrive out of order (a quick year or race change while
 *  an earlier fetch is still in flight): without it the slower, OLDER response
 *  lands last and overwrites the newer one. */
export function createLatestGuard() {
  let latest = 0;
  return {
    begin: () => ++latest,
    isCurrent: (token: number) => token === latest,
  };
}
