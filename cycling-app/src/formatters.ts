// Pure display-formatting helpers: time/gap strings, route-type colors, and
// the climbing-difficulty score. No DOM, no event wiring.
import type { StageInfo } from "./types";
import { state, raceConfig } from "./state";

export const PALETTE = [
  "#ffce00", "#ff6b6b", "#4dabf7", "#69db7c", "#da77f2",
  "#ff922b", "#22b8cf", "#f783ac", "#94d82d", "#9775fa",
  "#ffa94d", "#3bc9db", "#ff8787", "#63e6be", "#e599f7",
  "#74c0fc", "#ffd43b", "#b2f2bb", "#eebefa", "#a9e34b",
];

export function fmtTotalTime(seconds: number | null): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function stageLabel(stageNum: number): string {
  return state.dataset?.stages.find((s) => s.stage_number === stageNum)?.stage_label ?? String(stageNum);
}

/** Compact form for axis ticks and column headers. Falls back to the full
 *  label when a race defines no abbreviation. */
export function stageShortLabel(stageNum: number): string {
  const s = state.dataset?.stages.find((st) => st.stage_number === stageNum);
  return s?.stage_short_label ?? s?.stage_label ?? String(stageNum);
}

/** A stage's name in prose. Grand Tours read "Stage 12"; the classics read
 *  just "Paris-Roubaix", since each of their "stages" IS a race and prefixing
 *  it would give "Stage Paris-Roubaix". stage_label already carries the right
 *  text in both cases — this only decides the prefix. */
export function stageTitle(stageNum: number): string {
  const label = stageLabel(stageNum);
  return raceConfig().stagesAreRaces ? label : `Stage ${label}`;
}

/** Axis/column heading for the stage dimension. */
export function stageAxisLabel(): string {
  return raceConfig().stagesAreRaces ? "Race" : "Stage";
}

export function fmtGap(seconds: number | null, gcRank?: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds === 0 && gcRank === 1) return "leader";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts = h > 0 ? [h, m, s] : [m, s];
  return "+" + parts.map((p, i) => (i === 0 ? String(p) : String(p).padStart(2, "0"))).join(":");
}

/** Gap formatted as H:MM (seconds dropped), for the By Stage Table, where
 *  column width is tight. Hours are never padded, so a sub-hour gap reads as
 *  "0:25" rather than "25". */
export function fmtGapHM(seconds: number | null, gcRank?: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds === 0 && gcRank === 1) return "leader";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `+${h}:${String(m).padStart(2, "0")}`;
}

/** Zero-padded HH:MM:SS, for the GC Time y-axis. */
export function fmtHms(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

// ─── Route type colors & difficulty ──────────────────────────────────────────

export const ROUTE_COLOR: Record<string, string> = {
  P:   "#9b59b6",  // prologue — purple
  TT:  "#7f8c8d",  // time trial — gray
  TTT: "#95a5a6",  // team TT — light gray
  F:   "#27ae60",  // flat — green
  H:   "#e67e22",  // hilly — orange
  M:   "#e74c3c",  // mountain — red
  // Off-road. These two are not points on the F/H/M climbing scale — the
  // Athlinks data behind them carries no elevation at all, and PCS (which is
  // where ProfileScore comes from) does not cover these races. They encode
  // SURFACE, which is the property that actually separates an off-road race
  // from everything else here. Two earth tones, so the pair reads as one
  // family against the road palette.
  G:   "#c08457",  // gravel — dust
  X:   "#7a5230",  // mountain bike — dirt
};

export const ROUTE_LABEL: Record<string, string> = {
  P: "Prologue", TT: "Time Trial", TTT: "Team TT",
  F: "Flat", H: "Hilly", M: "Mountain",
  G: "Gravel", X: "Mountain Bike",
};

export const ROUTE_MULTIPLIER: Record<string, number> = {
  P: 0.3, TT: 0.5, TTT: 0.6, F: 1.0, H: 1.3, M: 1.8,
  // Only reachable once these races carry elevation — difficultyScore returns
  // 0 while vertical_meters is NULL, whatever the multiplier.
  G: 1.4, X: 1.8,
};

export function difficultyScore(stage: StageInfo): number {
  if (stage.profile_score != null) return stage.profile_score;
  const vm = stage.vertical_meters ?? 0;
  const dk = stage.distance_km ?? 0;
  if (dk === 0) return 0;
  const mult = ROUTE_MULTIPLIER[stage.route_type ?? "F"] ?? 1.0;
  return (vm * vm) / (dk * 1000) * mult;
}
