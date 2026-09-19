export interface StageInfo {
  stage_number: number;
  stage_label: string;
  /** Abbreviation for axis ticks and table headers, where the full
   *  stage_label is too wide ("LBL" for "Liege-Bastogne-Liege"). Only the
   *  one-day classics set this; Grand Tour stage labels are already short. */
  stage_short_label?: string;
  /** ISO 'YYYY-MM-DD'. Only the one-day classics export it so far — a season's
   *  race order is derived from it, and the column tooltip displays it. */
  stage_date?: string | null;
  start_location: string | null;
  finish_location: string | null;
  distance_km: number | null;
  vertical_meters: number | null;
  route_type: string | null; // 'F' | 'H' | 'M' | 'TT' | 'TTT'
  profile_score: number | null; // PCS's own grade-aware climbing-difficulty score
  /** WHAT FIELD THIS RACE'S RANKS ARE OVER. Off-road races only — a Grand Tour
   *  stage or a classic has one field and a rank is unambiguously a place in
   *  it. An off-road race is a mass start with categories inside it and the
   *  timer publishes a different slice from year to year, so without this,
   *  Leadville's rank 3 means "third man across the line" through 2015 and
   *  "third PRO" from 2016 with no way to tell. See fieldDefinitionLabel(). */
  field_definition?: string | null;
  cancelled?: boolean;
}

export interface RiderStagePoint {
  stage: number;
  gcRank: number | null;
  gcGapSeconds: number | null;
  status: string;
  cumulativePoints: number;
  cumulativeKomPoints: number;
  sprintRank: number | null;
  komRank: number | null;
}

export interface RiderSeries {
  id: string;
  name: string;         // "LastName FirstName" (PCS format)
  firstName?: string;   // parsed from PCS rider page; absent until scrape runs
  lastName?: string;
  nationality: string | null;
  team: string | null;
  finalRank: number;
  totalTimeSeconds: number | null;
  bibNumber: number | null;
  byStage: RiderStagePoint[];
  /** Result annulled after the fact — PCS strikes the rank through and keeps
   *  the number. Present only when true. The rider, the rank and the time are
   *  all kept deliberately; this only says the placing was taken away. */
  dq?: number;
}

export interface GcDataset {
  stages: StageInfo[];
  riders: RiderSeries[];
}
