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
  weather_constraint: boolean;
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

export interface ValidationResult {
  violations: Violation[];
  red_count: number;
  yellow_count: number;
  status: 'RED' | 'YELLOW' | 'GREEN';
}

export interface ScheduleSummary {
  total_games: number;
  games_per_team: Record<string, { home: number; away: number; total: number }>;
  rivalry_games: number;
  primetime_games: number;
  solver_status: string;
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

export type NavSection = 'schedule' | 'conflicts' | 'travel' | 'audience' | 'tournament';
