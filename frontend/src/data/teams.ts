import type { Team, Venue, League } from '../types';

export const VENUES: Venue[] = [
  { id: 'northside_arena', name: 'Northside Arena', city: 'Cary', capacity: 18000, latitude: 35.7915, longitude: -78.7811, is_outdoor: false },
  { id: 'thunder_dome', name: 'Thunder Dome', city: 'Charlotte', capacity: 20000, latitude: 35.2271, longitude: -80.8431, is_outdoor: false },
  { id: 'hawk_center', name: 'Hawk Center', city: 'Raleigh', capacity: 15000, latitude: 35.7796, longitude: -78.6382, is_outdoor: false },
  { id: 'blaze_stadium', name: 'Blaze Stadium', city: 'Durham', capacity: 16000, latitude: 35.9940, longitude: -78.8986, is_outdoor: true },
  { id: 'storm_pavilion', name: 'Storm Pavilion', city: 'Asheville', capacity: 12000, latitude: 35.5951, longitude: -82.5515, is_outdoor: false },
  { id: 'wolf_den_arena', name: 'Wolf Den Arena', city: 'Greensboro', capacity: 14000, latitude: 36.0726, longitude: -79.7920, is_outdoor: false },
  { id: 'tidal_wave_center', name: 'Tidal Wave Center', city: 'Wilmington', capacity: 11000, latitude: 34.2257, longitude: -77.9447, is_outdoor: false },
  { id: 'falcon_field', name: 'Falcon Field', city: 'Fayetteville', capacity: 13000, latitude: 35.0527, longitude: -78.8784, is_outdoor: true },
  { id: 'riverside_complex', name: 'Riverside Complex', city: 'Riverside', capacity: 10000, latitude: 35.3200, longitude: -80.6000, is_outdoor: false },
  { id: 'lakewood_center', name: 'Lakewood Center', city: 'Lakewood', capacity: 9500, latitude: 35.8500, longitude: -79.0500, is_outdoor: false },
  { id: 'oakridge_field', name: 'Oakridge Field', city: 'Oakridge', capacity: 11000, latitude: 36.1700, longitude: -79.9800, is_outdoor: true },
  { id: 'pinehurst_dome', name: 'Pinehurst Dome', city: 'Pinehurst', capacity: 8500, latitude: 35.1954, longitude: -79.4695, is_outdoor: false },
  { id: 'brookside_arena', name: 'Brookside Arena', city: 'Brookside', capacity: 9000, latitude: 35.5000, longitude: -78.5000, is_outdoor: false },
  { id: 'westgate_center', name: 'Westgate Center', city: 'Westgate', capacity: 12000, latitude: 35.9000, longitude: -80.3000, is_outdoor: false },
  { id: 'eastfield_stadium', name: 'Eastfield Stadium', city: 'Eastfield', capacity: 10500, latitude: 35.6000, longitude: -77.8000, is_outdoor: true },
  { id: 'northview_arena', name: 'Northview Arena', city: 'Northview', capacity: 11500, latitude: 36.4000, longitude: -79.2000, is_outdoor: false },
];

export const VENUES_BY_ID: Record<string, Venue> = Object.fromEntries(VENUES.map(v => [v.id, v]));

export const NPL_TEAMS: Team[] = [
  { id: 'cary_cobras', name: 'Cary Cobras', city: 'Cary', league: 'NPL', market_size: 'medium', home_venue_id: 'northside_arena', color: '#1E40AF' },
  { id: 'charlotte_thunder', name: 'Charlotte Thunder', city: 'Charlotte', league: 'NPL', market_size: 'large', home_venue_id: 'thunder_dome', color: '#7C3AED' },
  { id: 'raleigh_hawks', name: 'Raleigh Hawks', city: 'Raleigh', league: 'NPL', market_size: 'large', home_venue_id: 'hawk_center', color: '#DC2626' },
  { id: 'durham_blaze', name: 'Durham Blaze', city: 'Durham', league: 'NPL', market_size: 'medium', home_venue_id: 'blaze_stadium', color: '#D97706' },
  { id: 'asheville_storms', name: 'Asheville Storms', city: 'Asheville', league: 'NPL', market_size: 'small', home_venue_id: 'storm_pavilion', color: '#059669' },
  { id: 'greensboro_wolves', name: 'Greensboro Wolves', city: 'Greensboro', league: 'NPL', market_size: 'medium', home_venue_id: 'wolf_den_arena', color: '#6B7280' },
  { id: 'wilmington_tide', name: 'Wilmington Tide', city: 'Wilmington', league: 'NPL', market_size: 'small', home_venue_id: 'tidal_wave_center', color: '#0891B2' },
  { id: 'fayetteville_falcons', name: 'Fayetteville Falcons', city: 'Fayetteville', league: 'NPL', market_size: 'small', home_venue_id: 'falcon_field', color: '#BE123C' },
];

export const SAC_TEAMS: Team[] = [
  { id: 'riverside_lions', name: 'Riverside Lions', city: 'Riverside', league: 'SAC', market_size: 'medium', home_venue_id: 'riverside_complex', color: '#CA8A04' },
  { id: 'lakewood_bears', name: 'Lakewood Bears', city: 'Lakewood', league: 'SAC', market_size: 'small', home_venue_id: 'lakewood_center', color: '#92400E' },
  { id: 'oakridge_stallions', name: 'Oakridge Stallions', city: 'Oakridge', league: 'SAC', market_size: 'medium', home_venue_id: 'oakridge_field', color: '#065F46' },
  { id: 'pinehurst_eagles', name: 'Pinehurst Eagles', city: 'Pinehurst', league: 'SAC', market_size: 'small', home_venue_id: 'pinehurst_dome', color: '#1E3A8A' },
  { id: 'brookside_panthers', name: 'Brookside Panthers', city: 'Brookside', league: 'SAC', market_size: 'small', home_venue_id: 'brookside_arena', color: '#4C1D95' },
  { id: 'westgate_titans', name: 'Westgate Titans', city: 'Westgate', league: 'SAC', market_size: 'medium', home_venue_id: 'westgate_center', color: '#7F1D1D' },
  { id: 'eastfield_sharks', name: 'Eastfield Sharks', city: 'Eastfield', league: 'SAC', market_size: 'small', home_venue_id: 'eastfield_stadium', color: '#164E63' },
  { id: 'northview_knights', name: 'Northview Knights', city: 'Northview', league: 'SAC', market_size: 'medium', home_venue_id: 'northview_arena', color: '#1F2937' },
];

export const ALL_TEAMS: Team[] = [...NPL_TEAMS, ...SAC_TEAMS];
export const TEAMS_BY_ID: Record<string, Team> = Object.fromEntries(ALL_TEAMS.map(t => [t.id, t]));

export const LEAGUES: League[] = [
  { id: 'NPL', name: 'National Pro League', short_name: 'NPL', teams: NPL_TEAMS },
  { id: 'SAC', name: 'Southern Athletic Conference', short_name: 'SAC', teams: SAC_TEAMS },
];

export const DEFAULT_RIVALRY_PAIRS: Record<string, string[][]> = {
  NPL: [
    ['cary_cobras', 'charlotte_thunder'],
    ['raleigh_hawks', 'durham_blaze'],
    ['greensboro_wolves', 'asheville_storms'],
  ],
  SAC: [
    ['riverside_lions', 'lakewood_bears'],
    ['oakridge_stallions', 'westgate_titans'],
    ['pinehurst_eagles', 'northview_knights'],
  ],
};
