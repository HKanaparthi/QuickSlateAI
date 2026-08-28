import { useState, useMemo, useEffect } from 'react';
import { LEAGUES, DEFAULT_RIVALRY_PAIRS, NPL_TEAMS, SAC_TEAMS, VENUES } from '../data/teams';
import type { BroadcastContract, VenueBlackout, CBAProfile } from '../types';
import { getCBAProfiles } from '../utils/api';

interface ConstraintPanelProps {
  onGenerate: (params: {
    league_id: string;
    season_start: string;
    season_end: string;
    min_rest_days: number;
    max_travel_miles_per_week: number;
    primetime_slots: string[];
    rivalry_pairs: string[][];
    home_away_balanced: boolean;
    no_back_to_back_away: boolean;
    use_default_rivalries: boolean;
    max_games_per_slot_per_week: number;
    min_distinct_slots_per_week: number;
    even_distribution: boolean;
    target_games_per_week: number;
    games_per_week_tolerance: number;
    broadcast_contracts: BroadcastContract[];
    venue_blackouts: VenueBlackout[];
    travel_optimization_weight: number;
    cba_profile_id: string | null;
    games_per_pair: number;
    divisions: string[][];
    games_between_division_opponents: number;
    games_between_nondivision_opponents: number;
  }) => void;
  isLoading: boolean;
}

const TIMESLOTS = [
  { id: 'Saturday 8:00 PM', label: 'Sat 8:00 PM (Primetime)' },
  { id: 'Sunday 4:00 PM', label: 'Sun 4:00 PM (Afternoon)' },
  { id: 'Friday 7:00 PM', label: 'Fri 7:00 PM (Evening)' },
  { id: 'Monday 7:00 PM', label: 'Mon 7:00 PM' },
  { id: 'Tuesday 6:00 PM', label: 'Tue 6:00 PM' },
  { id: 'Wednesday 7:00 PM', label: 'Wed 7:00 PM' },
  { id: 'Thursday 7:00 PM', label: 'Thu 7:00 PM' },
];

const TIMESLOT_OPTIONS = [
  'Saturday 8:00 PM',
  'Sunday 4:00 PM',
  'Friday 7:00 PM',
  'Monday 7:00 PM',
  'Tuesday 6:00 PM',
  'Wednesday 7:00 PM',
  'Thursday 7:00 PM',
];

export default function ConstraintPanel({ onGenerate, isLoading }: ConstraintPanelProps) {
  const [cbaProfiles, setCbaProfiles] = useState<CBAProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);

  useEffect(() => {
    getCBAProfiles().then(setCbaProfiles).catch(() => {});
  }, []);

  const applyProfile = (profileId: string | null) => {
    setSelectedProfileId(profileId);
    if (!profileId) return;
    const profile = cbaProfiles.find(p => p.id === profileId);
    if (!profile) return;
    setMinRestDays(profile.min_rest_days);
    setMaxTravelMiles(profile.max_travel_miles_per_week);
    setNoBackToBackAway(profile.no_back_to_back_away);
    setHomeAwayBalanced(profile.home_away_balanced);
    setEvenDistribution(profile.even_distribution);
    setTargetGamesPerWeek(profile.target_games_per_week);
    setGamesPerWeekTolerance(profile.games_per_week_tolerance);
    setMinDistinctSlotsPerWeek(profile.min_distinct_slots_per_week);
    setMaxGamesPerSlotPerWeek(profile.max_games_per_slot_per_week);
    setTravelOptWeight(profile.travel_optimization_weight);
  };

  const [leagueId, setLeagueId] = useState('NPL');
  const [seasonStart, setSeasonStart] = useState('2026-10-01');
  const [seasonEnd, setSeasonEnd] = useState('2027-04-30');
  const [minRestDays, setMinRestDays] = useState(2);
  const [maxTravelMiles, setMaxTravelMiles] = useState(600);
  const [selectedSlots, setSelectedSlots] = useState<string[]>(['Saturday 8:00 PM', 'Sunday 4:00 PM', 'Friday 7:00 PM']);
  const [useDefaultRivalries, setUseDefaultRivalries] = useState(true);
  const [customRivalry1, setCustomRivalry1] = useState('');
  const [customRivalry2, setCustomRivalry2] = useState('');
  const [customRivalries, setCustomRivalries] = useState<string[][]>([]);
  const [homeAwayBalanced, setHomeAwayBalanced] = useState(true);
  const [noBackToBackAway, setNoBackToBackAway] = useState(true);
  // Opponent rotation
  const [useDivisions, setUseDivisions] = useState(false);
  const [gamesPerPair, setGamesPerPair] = useState(2);
  const [divisionAssignments, setDivisionAssignments] = useState<Record<string, number>>({});
  const [divGames, setDivGames] = useState(4);
  const [nonDivGames, setNonDivGames] = useState(2);
  const [maxGamesPerSlotPerWeek, setMaxGamesPerSlotPerWeek] = useState(2);
  const [minDistinctSlotsPerWeek, setMinDistinctSlotsPerWeek] = useState(3);
  const [evenDistribution, setEvenDistribution] = useState(true);
  const [targetGamesPerWeek, setTargetGamesPerWeek] = useState(4);
  const [gamesPerWeekTolerance, setGamesPerWeekTolerance] = useState(1);
  const [broadcastContracts, setBroadcastContracts] = useState<BroadcastContract[]>([]);
  const [venueBlackouts, setVenueBlackouts] = useState<VenueBlackout[]>([]);
  const [newBlackoutVenueId, setNewBlackoutVenueId] = useState('');
  const [newBlackoutStart, setNewBlackoutStart] = useState('');
  const [newBlackoutEnd, setNewBlackoutEnd] = useState('');
  const [newBlackoutReason, setNewBlackoutReason] = useState('');
  const [travelOptWeight, setTravelOptWeight] = useState(1.0);
  const [showConstraintArch, setShowConstraintArch] = useState(false);

  const currentTeams = leagueId === 'NPL' ? NPL_TEAMS : SAC_TEAMS;
  const currentVenues = useMemo(() => {
    const ids = new Set(currentTeams.map(t => t.home_venue_id));
    return VENUES.filter(v => ids.has(v.id));
  }, [currentTeams]);

  const addBroadcastContract = () => {
    setBroadcastContracts(prev => [
      ...prev,
      { network: 'ESPN', timeslot: 'Saturday 8:00 PM', required_games: 6, max_games: 10, rivalry_priority: false },
    ]);
  };

  const removeBroadcastContract = (i: number) => {
    setBroadcastContracts(prev => prev.filter((_, j) => j !== i));
  };

  const updateBroadcastContract = (i: number, field: keyof BroadcastContract, value: string | number | boolean) => {
    setBroadcastContracts(prev => prev.map((c, j) => j === i ? { ...c, [field]: value } : c));
  };

  const addVenueBlackout = () => {
    if (!newBlackoutVenueId || !newBlackoutStart || !newBlackoutEnd) return;
    if (newBlackoutEnd < newBlackoutStart) return;
    setVenueBlackouts(prev => [
      ...prev,
      { venue_id: newBlackoutVenueId, start_date: newBlackoutStart, end_date: newBlackoutEnd, reason: newBlackoutReason },
    ]);
    setNewBlackoutStart('');
    setNewBlackoutEnd('');
    setNewBlackoutReason('');
  };

  const removeVenueBlackout = (i: number) => {
    setVenueBlackouts(prev => prev.filter((_, j) => j !== i));
  };

  const toggleSlot = (slot: string) => {
    setSelectedSlots(prev =>
      prev.includes(slot) ? prev.filter(s => s !== slot) : [...prev, slot]
    );
  };

  const addRivalry = () => {
    if (customRivalry1 && customRivalry2 && customRivalry1 !== customRivalry2) {
      setCustomRivalries(prev => [...prev, [customRivalry1, customRivalry2]]);
      setCustomRivalry1('');
      setCustomRivalry2('');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const rivalryPairs = useDefaultRivalries
      ? DEFAULT_RIVALRY_PAIRS[leagueId] || []
      : customRivalries;

    // Build divisions array from team assignments
    const divisionsArray: string[][] = useDivisions
      ? [
          currentTeams.filter(t => (divisionAssignments[t.id] ?? 0) === 0).map(t => t.id),
          currentTeams.filter(t => (divisionAssignments[t.id] ?? 0) === 1).map(t => t.id),
        ].filter(d => d.length > 0)
      : [];

    onGenerate({
      league_id: leagueId,
      season_start: seasonStart,
      season_end: seasonEnd,
      min_rest_days: minRestDays,
      max_travel_miles_per_week: maxTravelMiles,
      primetime_slots: selectedSlots,
      rivalry_pairs: rivalryPairs,
      home_away_balanced: homeAwayBalanced,
      no_back_to_back_away: noBackToBackAway,
      use_default_rivalries: useDefaultRivalries,
      max_games_per_slot_per_week: maxGamesPerSlotPerWeek,
      min_distinct_slots_per_week: minDistinctSlotsPerWeek,
      even_distribution: evenDistribution,
      target_games_per_week: targetGamesPerWeek,
      games_per_week_tolerance: gamesPerWeekTolerance,
      broadcast_contracts: broadcastContracts,
      venue_blackouts: venueBlackouts,
      travel_optimization_weight: travelOptWeight,
      cba_profile_id: selectedProfileId,
      games_per_pair: useDivisions ? 2 : gamesPerPair,
      divisions: divisionsArray,
      games_between_division_opponents: divGames,
      games_between_nondivision_opponents: nonDivGames,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* League Selection */}
        <div className="card">
          <h3 className="section-title">League</h3>
          <div className="flex gap-3">
            {LEAGUES.map(lg => (
              <button
                key={lg.id}
                type="button"
                onClick={() => setLeagueId(lg.id)}
                className={[
                  'flex-1 py-2.5 px-4 rounded-lg border text-sm font-medium transition-all',
                  leagueId === lg.id
                    ? 'bg-primary-600 border-primary-600 text-white'
                    : 'border-dark-600 text-dark-500 hover:border-primary-600 hover:text-white',
                ].join(' ')}
              >
                <div className="font-bold">{lg.short_name}</div>
                <div className="text-xs opacity-75">{lg.name}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Season Dates */}
        <div className="card">
          <h3 className="section-title">Season Dates</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Start Date</label>
              <input
                type="date"
                value={seasonStart}
                onChange={e => setSeasonStart(e.target.value)}
                className="input w-full"
              />
            </div>
            <div>
              <label className="label">End Date</label>
              <input
                type="date"
                value={seasonEnd}
                onChange={e => setSeasonEnd(e.target.value)}
                className="input w-full"
              />
            </div>
          </div>
        </div>
      </div>

      {/* CBA Rule Profiles */}
      {cbaProfiles.length > 0 && (
        <div className="card">
          <div className="mb-3">
            <h3 className="section-title mb-0">CBA Rule Profile</h3>
            <p className="text-xs text-dark-600 mt-0.5">
              Apply a pre-configured league rule profile — auto-fills rest, travel, and distribution constraints below.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 mb-3">
            <button
              type="button"
              onClick={() => applyProfile(null)}
              className={[
                'py-2 px-3 rounded-lg border text-xs font-medium transition-all text-left',
                selectedProfileId === null
                  ? 'bg-dark-600 border-dark-500 text-white'
                  : 'border-dark-700 text-dark-600 hover:border-dark-500 hover:text-dark-400',
              ].join(' ')}
            >
              <div className="font-semibold">Custom</div>
              <div className="opacity-75 mt-0.5">Manual settings</div>
            </button>
            {cbaProfiles.map(profile => (
              <button
                key={profile.id}
                type="button"
                onClick={() => applyProfile(profile.id)}
                className={[
                  'py-2 px-3 rounded-lg border text-xs font-medium transition-all text-left',
                  selectedProfileId === profile.id
                    ? 'bg-primary-600/20 border-primary-600 text-white'
                    : 'border-dark-700 text-dark-600 hover:border-dark-500 hover:text-dark-400',
                ].join(' ')}
              >
                <div className="font-semibold">{profile.name}</div>
                <div className="opacity-75 mt-0.5 line-clamp-1">{profile.description}</div>
              </button>
            ))}
          </div>
          {selectedProfileId && (() => {
            const profile = cbaProfiles.find(p => p.id === selectedProfileId);
            if (!profile) return null;
            return (
              <div className="bg-dark-700/60 rounded-lg p-3 border border-primary-600/20">
                <div className="text-xs font-semibold text-primary-400 mb-2">
                  {profile.name} — Active Rules
                </div>
                <ul className="space-y-1">
                  {profile.rules.map((rule, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-dark-400">
                      <span className="text-success mt-0.5 flex-shrink-0">✓</span>
                      {rule}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-dark-600 mt-2">
                  Constraint sliders below have been updated to match this profile. You can still adjust them further.
                </p>
              </div>
            );
          })()}
        </div>
      )}

      {/* Constraint Sliders */}
      <div className="card">
        <h3 className="section-title">Scheduling Constraints</h3>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <div>
            <label className="label">
              Minimum Rest Days Between Games: <span className="text-primary-500 font-bold">{minRestDays}</span>
            </label>
            <input
              type="range" min={1} max={4} value={minRestDays}
              onChange={e => setMinRestDays(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>1 day</span><span>4 days</span>
            </div>
          </div>

          <div>
            <label className="label">
              Max Travel Miles/Week: <span className="text-primary-500 font-bold">{maxTravelMiles}</span>
            </label>
            <input
              type="range" min={200} max={1200} step={50} value={maxTravelMiles}
              onChange={e => setMaxTravelMiles(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>200 mi</span><span>1200 mi</span>
            </div>
          </div>
        </div>

          <div>
            <label className="label">
              Travel Optimization Weight: <span className="text-primary-500 font-bold">{travelOptWeight.toFixed(1)}</span>
            </label>
            <input
              type="range" min={0} max={2} step={0.1} value={travelOptWeight}
              onChange={e => setTravelOptWeight(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>0 (ignore)</span><span>2.0 (strongly minimize)</span>
            </div>
            <p className="text-xs text-dark-600 mt-1">
              Subtracts travel cost from the objective — optimizer actively routes shorter trips into better timeslots.
              At 1.0: a 1,000 mi trip costs ~10 objective pts (same scale as a timeslot score).
            </p>
          </div>

        <div className="mt-4 flex flex-wrap gap-4">
          <Toggle label="Home/Away Balanced" value={homeAwayBalanced} onChange={setHomeAwayBalanced} />
          <Toggle label="No Consecutive Away Games (CP-SAT)" value={noBackToBackAway} onChange={setNoBackToBackAway} />
        </div>
      </div>

      {/* Schedule Distribution */}
      <div className="card">
        <h3 className="section-title">Schedule Distribution</h3>
        <p className="text-xs text-dark-600 mb-4">
          Control how games are spread across timeslots and weeks to avoid clustering and primetime overload.
        </p>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <div>
            <label className="label">
              Max Games per Timeslot per Week:{' '}
              <span className="text-primary-500 font-bold">{maxGamesPerSlotPerWeek}</span>
            </label>
            <input
              type="range" min={1} max={3} value={maxGamesPerSlotPerWeek}
              onChange={e => setMaxGamesPerSlotPerWeek(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>1 (strict)</span><span>3 (relaxed)</span>
            </div>
            <p className="text-xs text-dark-600 mt-1">
              Prevents stacking — e.g. no 3× Saturday primetime games in one week.
            </p>
          </div>

          <div>
            <label className="label">
              Min Distinct Timeslots per Week:{' '}
              <span className="text-primary-500 font-bold">{minDistinctSlotsPerWeek}</span>
            </label>
            <input
              type="range" min={2} max={5} value={minDistinctSlotsPerWeek}
              onChange={e => setMinDistinctSlotsPerWeek(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>2 slots</span><span>5 slots</span>
            </div>
            <p className="text-xs text-dark-600 mt-1">
              Forces games across Fri, Sat, Sun, weekday evenings — not all in one slot.
            </p>
          </div>
        </div>

        <div className="mt-5 border-t border-dark-700 pt-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-dark-400">Even Weekly Distribution</span>
            <Toggle label="" value={evenDistribution} onChange={setEvenDistribution} />
          </div>
          {evenDistribution && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="label">
                  Target Games per Week:{' '}
                  <span className="text-primary-500 font-bold">{targetGamesPerWeek}</span>
                </label>
                <input
                  type="range" min={2} max={7} value={targetGamesPerWeek}
                  onChange={e => setTargetGamesPerWeek(+e.target.value)}
                  className="w-full accent-primary-600"
                />
                <div className="flex justify-between text-xs text-dark-600 mt-1">
                  <span>2/week (light)</span><span>7/week (heavy)</span>
                </div>
              </div>
              <div>
                <label className="label">
                  Tolerance (± games):{' '}
                  <span className="text-primary-500 font-bold">{gamesPerWeekTolerance}</span>
                </label>
                <input
                  type="range" min={0} max={3} value={gamesPerWeekTolerance}
                  onChange={e => setGamesPerWeekTolerance(+e.target.value)}
                  className="w-full accent-primary-600"
                />
                <div className="flex justify-between text-xs text-dark-600 mt-1">
                  <span>0 (exact)</span><span>3 (flexible)</span>
                </div>
              </div>
            </div>
          )}
          {evenDistribution && (
            <p className="text-xs text-dark-600 mt-2">
              Solver will aim for <strong className="text-dark-400">{targetGamesPerWeek - gamesPerWeekTolerance}–{targetGamesPerWeek + gamesPerWeekTolerance}</strong> games/week — no early-season clustering or late-season gaps.
            </p>
          )}
        </div>
      </div>

      {/* Time Slots */}
      <div className="card">
        <h3 className="section-title">Broadcast Time Slots</h3>
        <div className="flex flex-wrap gap-2">
          {TIMESLOTS.map(slot => (
            <button
              key={slot.id}
              type="button"
              onClick={() => toggleSlot(slot.id)}
              className={[
                'px-3 py-1.5 rounded-full text-sm font-medium border transition-all',
                selectedSlots.includes(slot.id)
                  ? 'bg-primary-600 border-primary-600 text-white'
                  : 'border-dark-600 text-dark-500 hover:border-primary-500',
              ].join(' ')}
            >
              {slot.label}
            </button>
          ))}
        </div>
      </div>

      {/* Broadcast Contracts */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="section-title mb-0">Broadcast Contracts</h3>
            <p className="text-xs text-dark-600 mt-0.5">
              Legally binding inventory commitments — solver enforces these as hard constraints.
            </p>
          </div>
          <button type="button" onClick={addBroadcastContract} className="btn-secondary text-xs px-3 py-1.5">
            + Add Contract
          </button>
        </div>

        {broadcastContracts.length === 0 && (
          <div className="text-xs text-dark-600 py-3 text-center border border-dashed border-dark-700 rounded-lg">
            No broadcaster contracts configured — add one to enforce minimum game commitments per timeslot.
          </div>
        )}

        <div className="space-y-3">
          {broadcastContracts.map((contract, i) => (
            <div key={i} className="bg-dark-700/60 rounded-lg p-3 border border-dark-600">
              <div className="flex items-center justify-between mb-2.5">
                <input
                  type="text"
                  value={contract.network}
                  onChange={e => updateBroadcastContract(i, 'network', e.target.value)}
                  placeholder="Network (ESPN, FOX…)"
                  className="input text-sm font-semibold w-32"
                />
                <button type="button" onClick={() => removeBroadcastContract(i)} className="text-danger text-xs hover:opacity-75">
                  Remove
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="label text-xs">Timeslot</label>
                  <select
                    value={contract.timeslot}
                    onChange={e => updateBroadcastContract(i, 'timeslot', e.target.value)}
                    className="input text-xs w-full"
                  >
                    {TIMESLOT_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label text-xs">Required</label>
                  <input
                    type="number" min={0} max={30}
                    value={contract.required_games}
                    onChange={e => updateBroadcastContract(i, 'required_games', +e.target.value)}
                    className="input text-sm w-full"
                  />
                </div>
                <div>
                  <label className="label text-xs">Max</label>
                  <input
                    type="number" min={0} max={50}
                    value={contract.max_games}
                    onChange={e => updateBroadcastContract(i, 'max_games', +e.target.value)}
                    className="input text-sm w-full"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Venue Availability */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="section-title mb-0">Venue Availability</h3>
            <p className="text-xs text-dark-600 mt-0.5">
              Block venues during concerts, renovations, or conflicting events — solver will not schedule games during these windows.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 mb-3 sm:grid-cols-4">
          <div>
            <label className="label text-xs">Venue</label>
            <select
              value={newBlackoutVenueId}
              onChange={e => setNewBlackoutVenueId(e.target.value)}
              className="input text-xs w-full"
            >
              <option value="">Select venue…</option>
              {currentVenues.map(v => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label text-xs">From</label>
            <input
              type="date"
              value={newBlackoutStart}
              onChange={e => setNewBlackoutStart(e.target.value)}
              className="input text-xs w-full"
            />
          </div>
          <div>
            <label className="label text-xs">To</label>
            <input
              type="date"
              value={newBlackoutEnd}
              onChange={e => setNewBlackoutEnd(e.target.value)}
              className="input text-xs w-full"
            />
          </div>
          <div className="flex items-end">
            <button
              type="button"
              onClick={addVenueBlackout}
              disabled={!newBlackoutVenueId || !newBlackoutStart || !newBlackoutEnd}
              className="btn-secondary text-xs px-3 py-2 w-full disabled:opacity-40"
            >
              + Block
            </button>
          </div>
        </div>

        {newBlackoutVenueId && newBlackoutStart && (
          <div className="mb-3">
            <input
              type="text"
              value={newBlackoutReason}
              onChange={e => setNewBlackoutReason(e.target.value)}
              placeholder="Reason (optional — e.g. Concert series, Renovation)"
              className="input text-xs w-full"
            />
          </div>
        )}

        {venueBlackouts.length === 0 ? (
          <div className="text-xs text-dark-600 py-3 text-center border border-dashed border-dark-700 rounded-lg">
            No venue blackouts configured — all venues are available for the full season.
          </div>
        ) : (
          <div className="space-y-2">
            {venueBlackouts.map((b, i) => {
              const venue = currentVenues.find(v => v.id === b.venue_id);
              return (
                <div key={i} className="flex items-center justify-between bg-dark-700/60 rounded-lg px-3 py-2 text-xs border border-dark-600">
                  <div>
                    <span className="font-medium text-white">{venue?.name ?? b.venue_id}</span>
                    <span className="text-dark-500 mx-2">·</span>
                    <span className="text-dark-400">{b.start_date} → {b.end_date}</span>
                    {b.reason && <span className="text-dark-600 ml-2">({b.reason})</span>}
                  </div>
                  <button
                    type="button"
                    onClick={() => removeVenueBlackout(i)}
                    className="text-danger hover:opacity-75 ml-3"
                  >
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Constraint Architecture */}
      <div className="card">
        <button
          type="button"
          onClick={() => setShowConstraintArch(v => !v)}
          className="flex items-center justify-between w-full text-left"
        >
          <div>
            <h3 className="section-title mb-0">Constraint Architecture</h3>
            <p className="text-xs text-dark-600 mt-0.5">How the optimizer classifies and enforces constraints</p>
          </div>
          <span className="text-dark-500 text-sm">{showConstraintArch ? '▲' : '▼'}</span>
        </button>

        {showConstraintArch && (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-2 h-2 rounded-full bg-danger" />
                <span className="text-xs font-semibold text-white uppercase tracking-wide">Hard Constraints</span>
                <span className="text-xs text-dark-600">(solver MUST satisfy)</span>
              </div>
              <ul className="space-y-1.5 text-xs text-dark-400">
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Venue exclusivity — one game per venue per slot</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Minimum rest days between games</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>No consecutive away games — CP-SAT hard constraint</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Weekly travel cap — max miles per team per week</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Broadcaster commitments — required game counts per timeslot</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Venue availability — blackout windows fully blocked from solver</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Opponent rotation — configurable games per matchup pair</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Weekly game-volume band — no feast-or-famine weeks</li>
                <li className="flex items-start gap-2"><span className="text-success mt-0.5">✓</span>Season spacing — games every 1–2 weeks, never 3 consecutive idle</li>
              </ul>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-2 h-2 rounded-full bg-warning" />
                <span className="text-xs font-semibold text-white uppercase tracking-wide">Soft Constraints</span>
                <span className="text-xs text-dark-600">(optimizer targets)</span>
              </div>
              <ul className="space-y-1.5 text-xs text-dark-400">
                <li className="flex items-start gap-2"><span className="text-primary-500 mt-0.5">→</span>Primetime placement for rivalry games (+20 score bonus)</li>
                <li className="flex items-start gap-2"><span className="text-primary-500 mt-0.5">→</span>Travel minimization — long away trips penalized in objective</li>
                <li className="flex items-start gap-2"><span className="text-primary-500 mt-0.5">→</span>Viewership maximization via slot multipliers</li>
                <li className="flex items-start gap-2"><span className="text-warning mt-0.5">~</span>Home/away balance — validated post-solve (yellow warning if &gt;15% gap)</li>
              </ul>
            </div>
          </div>
        )}
      </div>

      {/* Opponent Rotation */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="section-title mb-0">Opponent Rotation</h3>
            <p className="text-xs text-dark-600 mt-0.5">
              How many times each pair of teams plays. Use divisions for conference-style structures.
            </p>
          </div>
          <Toggle label="Use divisions" value={useDivisions} onChange={v => { setUseDivisions(v); if (!v) setDivisionAssignments({}); }} />
        </div>

        {!useDivisions ? (
          <div>
            <label className="label">
              Games per matchup (each pair):{' '}
              <span className="text-primary-500 font-bold">{gamesPerPair}</span>
            </label>
            <input
              type="range" min={1} max={4} value={gamesPerPair}
              onChange={e => setGamesPerPair(+e.target.value)}
              className="w-full accent-primary-600"
            />
            <div className="flex justify-between text-xs text-dark-600 mt-1">
              <span>1 game (one-way)</span><span>4 games</span>
            </div>
            <p className="text-xs text-dark-600 mt-1">
              {gamesPerPair === 2
                ? 'Default: each pair plays once home, once away — perfectly balanced.'
                : gamesPerPair === 1
                ? '1 game per pair: home team determined by seeding order. Total games = n×(n-1)/2.'
                : `${gamesPerPair} games per pair: home games split as evenly as possible.`}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Division games (each pair):{' '}
                  <span className="text-primary-500 font-bold">{divGames}</span>
                </label>
                <input type="range" min={2} max={6} step={2} value={divGames}
                  onChange={e => setDivGames(+e.target.value)} className="w-full accent-primary-600" />
                <div className="flex justify-between text-xs text-dark-600 mt-1"><span>2</span><span>6</span></div>
              </div>
              <div>
                <label className="label">Non-division games (each pair):{' '}
                  <span className="text-primary-500 font-bold">{nonDivGames}</span>
                </label>
                <input type="range" min={1} max={4} value={nonDivGames}
                  onChange={e => setNonDivGames(+e.target.value)} className="w-full accent-primary-600" />
                <div className="flex justify-between text-xs text-dark-600 mt-1"><span>1</span><span>4</span></div>
              </div>
            </div>
            <div>
              <p className="text-xs text-dark-500 font-medium mb-2">Assign teams to divisions:</p>
              <div className="space-y-1.5">
                {currentTeams.map(t => {
                  const div = divisionAssignments[t.id] ?? 0;
                  return (
                    <div key={t.id} className="flex items-center justify-between bg-dark-700/60 rounded px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: t.color }} />
                        <span className="text-sm text-dark-400">{t.name}</span>
                      </div>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => setDivisionAssignments(prev => ({ ...prev, [t.id]: 0 }))}
                          className={`px-2 py-0.5 rounded text-xs font-medium transition-all ${div === 0 ? 'bg-primary-600 text-white' : 'border border-dark-600 text-dark-500 hover:border-primary-600'}`}
                        >Div 1</button>
                        <button
                          type="button"
                          onClick={() => setDivisionAssignments(prev => ({ ...prev, [t.id]: 1 }))}
                          className={`px-2 py-0.5 rounded text-xs font-medium transition-all ${div === 1 ? 'bg-warning text-dark-900' : 'border border-dark-600 text-dark-500 hover:border-warning'}`}
                        >Div 2</button>
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-dark-600 mt-2">
                Div 1:{' '}
                <span className="text-dark-400">{currentTeams.filter(t => (divisionAssignments[t.id] ?? 0) === 0).length} teams</span>
                {' · '}Div 2:{' '}
                <span className="text-dark-400">{currentTeams.filter(t => (divisionAssignments[t.id] ?? 0) === 1).length} teams</span>
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Rivalry Games */}
      <div className="card">
        <h3 className="section-title">Rivalry Games</h3>
        <label className="flex items-center gap-2 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={useDefaultRivalries}
            onChange={e => setUseDefaultRivalries(e.target.checked)}
            className="w-4 h-4 accent-primary-600"
          />
          <span className="text-sm text-dark-500">
            Use default {leagueId} rivalry pairs (3 built-in matchups)
          </span>
        </label>

        {!useDefaultRivalries && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <select value={customRivalry1} onChange={e => setCustomRivalry1(e.target.value)} className="input flex-1">
                <option value="">Team 1</option>
                {currentTeams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <select value={customRivalry2} onChange={e => setCustomRivalry2(e.target.value)} className="input flex-1">
                <option value="">Team 2</option>
                {currentTeams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <button type="button" onClick={addRivalry} className="btn-secondary px-3">
                Add
              </button>
            </div>
            {customRivalries.map((pair, i) => (
              <div key={i} className="flex items-center justify-between bg-dark-700 rounded px-3 py-2 text-sm">
                <span className="text-dark-400">{pair[0]} vs {pair[1]}</span>
                <button
                  type="button"
                  onClick={() => setCustomRivalries(prev => prev.filter((_, j) => j !== i))}
                  className="text-danger text-xs hover:opacity-75"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        {useDefaultRivalries && (
          <div className="space-y-1.5">
            {(DEFAULT_RIVALRY_PAIRS[leagueId] || []).map(([t1, t2], i) => (
              <div key={i} className="flex items-center gap-2 text-sm text-dark-400 bg-dark-700/50 rounded px-3 py-1.5">
                <span className="text-warning">⚡</span>
                <span>{t1.replace(/_/g, ' ')} vs {t2.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        type="submit"
        disabled={isLoading}
        className="btn-primary w-full py-3 text-base font-semibold disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
            Optimizing Schedule...
          </>
        ) : (
          <>✨ Generate AI Schedule</>
        )}
      </button>
    </form>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <div
        onClick={() => onChange(!value)}
        className={[
          'relative w-10 h-5 rounded-full transition-colors',
          value ? 'bg-primary-600' : 'bg-dark-600',
        ].join(' ')}
      >
        <div
          className={[
            'absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform',
            value ? 'translate-x-5' : 'translate-x-0.5',
          ].join(' ')}
        />
      </div>
      <span className="text-sm text-dark-400">{label}</span>
    </label>
  );
}
