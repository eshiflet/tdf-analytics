export interface StageInfo {
  stage_number: number;
  stage_label: string;
  start_location: string | null;
  finish_location: string | null;
  distance_km: number | null;
  vertical_meters: number | null;
  route_type: string | null; // 'F' | 'H' | 'M' | 'TT' | 'TTT'
  profile_score: number | null; // PCS's own grade-aware climbing-difficulty score
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
  name: string;
  nationality: string | null;
  team: string | null;
  finalRank: number;
  totalTimeSeconds: number | null;
  byStage: RiderStagePoint[];
}

export interface GcDataset {
  stages: StageInfo[];
  riders: RiderSeries[];
}
