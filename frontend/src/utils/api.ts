import axios from 'axios';
import type { TravelAnalysis, AudienceAnalysis, TournamentBracket } from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '/api';

const api = axios.create({ baseURL: BASE_URL });

export async function getLeagues() {
  const res = await api.get('/schedule/leagues');
  return res.data;
}

export async function getVenues() {
  const res = await api.get('/schedule/venues');
  return res.data;
}

export async function generateSchedule(payload: {
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
  use_default_rivalries: boolean;
  max_games_per_slot_per_week: number;
  min_distinct_slots_per_week: number;
  even_distribution: boolean;
  target_games_per_week: number;
  games_per_week_tolerance: number;
}) {
  const res = await api.post('/schedule/generate', payload);
  return res.data;
}

export async function getSchedule(scheduleId: string) {
  const res = await api.get(`/schedule/${scheduleId}`);
  return res.data;
}

export async function updateGame(scheduleId: string, gameId: string, newDate: string, newTimeslot: string) {
  const res = await api.post(`/schedule/${scheduleId}/update-game`, {
    game_id: gameId,
    new_date: newDate,
    new_timeslot: newTimeslot,
  });
  return res.data;
}

export async function explainGame(scheduleId: string, gameId: string) {
  const res = await api.get(`/schedule/${scheduleId}/game/${gameId}/explain`);
  return res.data;
}

export async function getTravelAnalysis(scheduleId: string): Promise<TravelAnalysis> {
  const res = await api.get(`/travel/${scheduleId}`);
  return res.data;
}

export async function getAudienceAnalysis(scheduleId: string): Promise<AudienceAnalysis> {
  const res = await api.get(`/audience/${scheduleId}`);
  return res.data;
}

export async function generateTournament(payload: {
  team_names: string[];
  format: string;
  num_fields: number;
  pools: number;
  game_duration_minutes: number;
  break_minutes: number;
}): Promise<TournamentBracket> {
  const res = await api.post('/tournament/generate', payload);
  return res.data;
}
