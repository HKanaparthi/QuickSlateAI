import { useState } from 'react';
import { LEAGUES, DEFAULT_RIVALRY_PAIRS, NPL_TEAMS, SAC_TEAMS } from '../data/teams';
import type { Team } from '../types';

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
    weather_constraint: boolean;
    use_default_rivalries: boolean;
    max_games_per_slot_per_week: number;
    min_distinct_slots_per_week: number;
    even_distribution: boolean;
    target_games_per_week: number;
    games_per_week_tolerance: number;
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

export default function ConstraintPanel({ onGenerate, isLoading }: ConstraintPanelProps) {
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
  const [weatherConstraint, setWeatherConstraint] = useState(false);
  const [maxGamesPerSlotPerWeek, setMaxGamesPerSlotPerWeek] = useState(2);
  const [minDistinctSlotsPerWeek, setMinDistinctSlotsPerWeek] = useState(3);
  const [evenDistribution, setEvenDistribution] = useState(true);
  const [targetGamesPerWeek, setTargetGamesPerWeek] = useState(4);
  const [gamesPerWeekTolerance, setGamesPerWeekTolerance] = useState(1);

  const currentTeams = leagueId === 'NPL' ? NPL_TEAMS : SAC_TEAMS;

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
      weather_constraint: weatherConstraint,
      use_default_rivalries: useDefaultRivalries,
      max_games_per_slot_per_week: maxGamesPerSlotPerWeek,
      min_distinct_slots_per_week: minDistinctSlotsPerWeek,
      even_distribution: evenDistribution,
      target_games_per_week: targetGamesPerWeek,
      games_per_week_tolerance: gamesPerWeekTolerance,
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

        <div className="mt-4 flex flex-wrap gap-4">
          <Toggle label="Home/Away Balanced" value={homeAwayBalanced} onChange={setHomeAwayBalanced} />
          <Toggle label="No Back-to-Back Away Games" value={noBackToBackAway} onChange={setNoBackToBackAway} />
          <Toggle label="Weather Constraints (outdoor venues)" value={weatherConstraint} onChange={setWeatherConstraint} />
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
