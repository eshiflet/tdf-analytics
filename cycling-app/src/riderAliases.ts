// ─── Merged-rider redirects ──────────────────────────────────────────────────
// Merging two rider ids deletes one of them, and every link anyone ever made to
// it goes dead: a bookmark, a shared URL, a search result all land on "No rider
// matches this link." 142 ids have been absorbed that way. The bug report that
// started the 2026-09-18 merge pass was itself a link to `rider/torbj-r`, which
// that pass deleted — the reporter's own URL stopped working as a result of
// reporting it.
//
// pipeline/link_rider_race_sets.py writes the map (see build_alias_map), and
// exports only entries whose canonical is really in an index, so a redirect
// here can never land on another dead page.
//
// FETCHED ONLY ON A MISS. The happy path — every link that still resolves —
// never touches this file, so the redirect costs nothing until it is needed.
// That is also why it is not folded into riders_index.json: this is 5 KB that
// almost nobody should ever download.
import aliasMapUrl from "./data/rider_aliases.json?url";

type AliasMap = Record<string, string>;

let pending: Promise<AliasMap> | null = null;

function loadAliasMap(): Promise<AliasMap> {
  // Cached as the PROMISE, not the result: two rider pages opened in quick
  // succession would otherwise each start their own fetch.
  pending ??= fetch(aliasMapUrl)
    .then((r) => (r.ok ? r.json() : {}))
    // A failed fetch must not turn a "no such rider" message into an exception.
    // Falling back to an empty map degrades to exactly the old behaviour.
    .catch(() => ({} as AliasMap));
  return pending;
}

/** The id this one was merged into, or null if it was never merged.
 *
 *  Takes and returns a full `rider/<slug>` id; the map itself is keyed on bare
 *  slugs, which is how riders_index.json stores them.
 *
 *  One hop only. An alias may never point at another alias — that is an
 *  invariant of rider_aliases.json with its own test on the pipeline side
 *  (test_no_alias_points_at_another_alias), not an assumption made here. */
export async function canonicalRiderId(riderId: string): Promise<string | null> {
  const slug = riderId.replace(/^rider\//, "");
  const target = (await loadAliasMap())[slug];
  return target && target !== slug ? `rider/${target}` : null;
}
