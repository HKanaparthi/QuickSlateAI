export interface Venue {
  id: string;
  name: string;
  city: string;
  capacity: number;
  latitude: number;
  longitude: number;
  is_outdoor: boolean;
}

export interface Team {
  id: string;
  name: string;
  city: string;
  league: string;
  market_size: 'large' | 'medium' | 'small';
  home_venue_id: string;
  color: string;
}

export interface League {
  id: string;
  name: string;
  short_name: string;
  teams: Team[];
}

export interface BroadcastContract {
  network: string;
  timeslot: string;
  required_games: number;
  max_games: number;
  rivalry_priority: boolean;
}

export interface VenueBlackout {
  venue_id: string;
  start_date: string;
  end_date: string;
  reason: string;
}

export interface ScoreBreakdown {
  timeslot_score: number;
  rivalry_bonus: number;
  travel_miles: number;
  travel_budget_pct: number;
  travel_penalty: number;
  total_objective_score: number;
  summary: string;
}

export interface Game {
  id: string;
  home_team_id: string;
  away_team_id: string;
  venue_id: string;
  game_date: string;
  timeslot: string;
  is_rivalry: boolean;
  ai_explanation: string | null;
  projected_viewership: number | null;
  travel_miles?: number;
  score_breakdown?: ScoreBreakdown;
}

export interface ScheduleConstraints {
  league_id: string;
  season_start: string;
  season_end: string;
  min_rest_days: number;
  max_travel_miles_per_week: number;
  primetime_slots: string[];
  rivalry_pairs: string[][];
  home_away_balanced: boolean;
  no_back_to_back_away: boolean;
  broadcast_contracts: BroadcastContract[];
  games_per_pair: number;
  divisions: string[][];
  games_between_division_opponents: number;
  games_between_nondivision_opponents: number;
}

export interface Schedule {
  id: string;
  league_id: string;
  season_start: string;
  season_end: string;
  games: Game[];
  constraints: ScheduleConstraints;
  total_games: number;
  generated_at: string;
  solver_status: string;
}

export interface Violation {
  type: string;
  severity: 'RED' | 'YELLOW' | 'GREEN';
  message: string;
  team_id?: string;
  game1_id?: string;
  game2_id?: string;
  venue_id?: string;
  game_ids?: string[];
}

export interface BroadcastComplianceItem {
  network: string;
  timeslot: string;
  required: number;
  max: number;
  actual: number;
  status: 'OK' | 'UNDER' | 'OVER';
}

export interface ValidationResult {
  violations: Violation[];
  red_count: number;
  yellow_count: number;
  status: 'RED' | 'YELLOW' | 'GREEN';
  broadcast_compliance: BroadcastComplianceItem[];
}

export interface FeasibilityIssue {
  type: string;
  severity: 'hard' | 'soft' | 'warning';
  message: string;
  suggestion?: string;
  network?: string;
}

export interface FeasibilityAnalysis {
  is_feasible_estimate: boolean;
  total_games: number;
  available_slots: number;
  season_days: number;
  games_per_team: number;
  issues: FeasibilityIssue[];
  warnings: string[];
}

export interface ScheduleSummary {
  total_games: number;
  games_per_team: Record<string, { home: number; away: number; total: number }>;
  rivalry_games: number;
  primetime_games: number;
  solver_status: string;
  avg_home_away_imbalance_pct?: number;
}

export interface TravelLeg {
  from_city: string;
  to_city: string;
  from_lat: number;
  from_lng: number;
  to_lat: number;
  to_lng: number;
  distance_miles: number;
  game_date: string;
  game_id: string;
}

export interface TeamTravelStats {
  team_id: string;
  team_name: string;
  total_miles: number;
  avg_miles_per_week: number;
  longest_trip_miles: number;
  travel_legs: TravelLeg[];
  weekly_miles: Record<string, number>;
  home_venue: { id: string; name: string; city: string; lat: number; lng: number };
}

export interface HotelSuggestion {
  team_id: string;
  team_name: string;
  game1_date: string;
  game1_city: string;
  game2_date: string;
  game2_city: string;
  stay_city: string;
  distance_between_games: number;
  savings_miles: number;
  message: string;
}

export interface TravelAnalysis {
  team_stats: Record<string, TeamTravelStats>;
  league_avg_miles: number;
  fairness_analysis: Array<{
    team_id: string;
    team_name: string;
    total_miles: number;
    pct_vs_avg: number;
    flagged: boolean;
  }>;
  hotel_suggestions: HotelSuggestion[];
  venues: Array<{ id: string; name: string; city: string; lat: number; lng: number; capacity: number }>;
}

export interface GameAudienceEstimate {
  game_id: string;
  projected_viewership: number;
  base_viewership: number;
  game_date: string;
  timeslot: string;
  home_team: string;
  away_team: string;
  is_rivalry: boolean;
  factors: {
    slot: string;
    slot_multiplier: number;
    is_rivalry: boolean;
    rivalry_multiplier: number;
    home_market: string;
    away_market: string;
    market_multiplier: number;
  };
  factor_contributions: {
    timeslot: string;
    rivalry: string;
    market_size: string;
  };
}

export interface AudienceAnalysis {
  game_estimates: GameAudienceEstimate[];
  total_projected_viewership: number;
  avg_viewership_per_game: number;
  peak_games: GameAudienceEstimate[];
  low_games: GameAudienceEstimate[];
  timeslot_analysis: Record<string, { count: number; total: number; avg: number }>;
  rivalry_premium: string;
}

export interface TournamentMatchup {
  id: string;
  team1: string | null;
  team2: string | null;
  winner: string | null;
  field: string;
  is_bye: boolean;
  round: number;
}

export interface TournamentRound {
  round: number;
  name: string;
  matchups: TournamentMatchup[];
}

export interface TournamentBracket {
  format: string;
  teams: string[];
  total_rounds?: number;
  total_games?: number;
  rounds?: TournamentRound[];
  pool_stages?: Array<{ pool: string; schedule: TournamentBracket }>;
  knockout_stage?: TournamentBracket;
  champion: string | null;
}

export type NavSection = 'schedule' | 'conflicts' | 'travel' | 'audience' | 'tournament' | 'repair';

export interface GameMove {
  game_id: string;
  original_date: string;
  original_timeslot: string;
  repaired_date: string;
  repaired_timeslot: string;
  displacement_days: number;
}

export interface RepairApiResponse {
  original_schedule_id: string;
  repaired_schedule_id: string | null;
  status: string;
  moves: GameMove[];
  neighborhood_expansions_used?: number;
  solve_time_seconds?: number;
  objective_gap?: number | null;
  validation_result?: ValidationResult | null;
  affected_game_ids?: string[];
  error_message?: string | null;
  message?: string;
}

export interface ComparisonMovedGame {
  game_id: string;
  home_team_id: string;
  away_team_id: string;
  original_date: string;
  original_timeslot: string;
  repaired_date: string;
  repaired_timeslot: string;
  displacement_days: number;
  original_projected_viewership: number | null;
  repaired_projected_viewership: number | null;
}

export interface ComparisonMetrics {
  total_games: number;
  games_moved: number;
  games_unchanged: number;
  total_displacement_days: number;
  original_total_quality: number;
  repaired_total_quality: number;
  quality_delta: number;
  moved_games: ComparisonMovedGame[];
}

export interface CBAProfile {
  id: string;
  name: string;
  description: string;
  rules: string[];
  min_rest_days: number;
  max_travel_miles_per_week: number;
  no_back_to_back_away: boolean;
  home_away_balanced: boolean;
  even_distribution: boolean;
  target_games_per_week: number;
  games_per_week_tolerance: number;
  min_distinct_slots_per_week: number;
  max_games_per_slot_per_week: number;
  travel_optimization_weight: number;
}

export interface SolverMetrics {
  decisions_evaluated: number;
  solve_time_seconds: number;
  total_variables: number;
  hard_constraints_count: number;
  solver_status: string;
  objective_value: number | null;
  infeasibility_reasons: string[];
  n_teams: number;
  n_matchups: number;
  n_slots: number;
  venue_conflicts: number;
  rest_violations: number;
  back_to_back_away_count: number;
  home_away_imbalance_count: number;
  broadcaster_satisfied: number;
  broadcaster_total: number;
  cba_profile_applied: string | null;
}
