import { useState, useMemo } from 'react';
import type { Game, Schedule, ValidationResult, ScheduleSummary } from '../types';
import { TEAMS_BY_ID, VENUES_BY_ID } from '../data/teams';
import GameCard from './GameCard';
import { explainGame } from '../utils/api';

interface ScheduleGridProps {
  schedule: Schedule;
  validation: ValidationResult;
  summary: ScheduleSummary;
}

export default function ScheduleGrid({ schedule, validation, summary }: ScheduleGridProps) {
  const [selectedGame, setSelectedGame] = useState<Game | null>(null);
  const [filterTeam, setFilterTeam] = useState('');
  const [viewMode, setViewMode] = useState<'week' | 'list'>('week');

  const teams = useMemo(() => {
    const ids = new Set<string>();
    schedule.games.forEach(g => { ids.add(g.home_team_id); ids.add(g.away_team_id); });
    return [...ids].map(id => TEAMS_BY_ID[id]).filter(Boolean);
  }, [schedule]);

  const filteredGames = useMemo(() => {
    if (!filterTeam) return schedule.games;
    return schedule.games.filter(
      g => g.home_team_id === filterTeam || g.away_team_id === filterTeam
    );
  }, [schedule.games, filterTeam]);

  const weeklyGroups = useMemo(() => {
    const groups: Record<string, Game[]> = {};
    filteredGames.forEach(g => {
      const d = new Date(g.game_date);
      const startOfWeek = new Date(d);
      startOfWeek.setDate(d.getDate() - d.getDay());
      const key = startOfWeek.toISOString().split('T')[0];
      groups[key] = groups[key] || [];
      groups[key].push(g);
    });
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [filteredGames]);

  const statusColor = { RED: 'text-danger', YELLOW: 'text-warning', GREEN: 'text-success' };

  return (
    <div className="space-y-5">
      {/* Summary Bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Total Games" value={summary.total_games} icon="🎮" />
        <StatCard label="Rivalry Games" value={summary.rivalry_games} icon="⚡" />
        <StatCard label="Primetime Slots" value={summary.primetime_games} icon="📺" />
        <div className="card flex items-center gap-3">
          <span className="text-2xl">
            {validation.status === 'GREEN' ? '✅' : validation.status === 'YELLOW' ? '⚠️' : '🔴'}
          </span>
          <div>
            <p className="text-xs text-dark-600">Schedule Status</p>
            <p className={`font-bold text-sm ${statusColor[validation.status]}`}>
              {validation.status === 'GREEN'
                ? 'All Clear'
                : `${validation.red_count} Critical, ${validation.yellow_count} Warnings`}
            </p>
          </div>
        </div>
      </div>

      {/* Filters & View Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <select
            value={filterTeam}
            onChange={e => setFilterTeam(e.target.value)}
            className="input text-sm"
          >
            <option value="">All Teams</option>
            {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>

        <div className="flex items-center gap-1 bg-dark-700 rounded-lg p-1">
          <button
            onClick={() => setViewMode('week')}
            className={`px-3 py-1 rounded text-sm font-medium transition-all ${viewMode === 'week' ? 'bg-primary-600 text-white' : 'text-dark-500 hover:text-white'}`}
          >
            Week View
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-3 py-1 rounded text-sm font-medium transition-all ${viewMode === 'list' ? 'bg-primary-600 text-white' : 'text-dark-500 hover:text-white'}`}
          >
            List View
          </button>
        </div>
      </div>

      {/* Solver Status */}
      {schedule.solver_status === 'GREEDY_FALLBACK' && (
        <div className="bg-warning/10 border border-warning/30 rounded-lg p-3 text-sm text-warning">
          Schedule generated with greedy fallback (OR-Tools timeout). Some constraints may be relaxed.
        </div>
      )}

      {/* Content */}
      {viewMode === 'week' ? (
        <WeekView groups={weeklyGroups} onGameClick={setSelectedGame} scheduleId={schedule.id} />
      ) : (
        <ListView games={filteredGames} onGameClick={setSelectedGame} scheduleId={schedule.id} />
      )}

      {/* Game Card Modal */}
      {selectedGame && (
        <GameCard
          game={selectedGame}
          onClose={() => setSelectedGame(null)}
          onExplain={async () => {
            const res = await explainGame(schedule.id, selectedGame.id);
            setSelectedGame(prev => prev ? { ...prev, ai_explanation: res.explanation } : null);
            return res.explanation;
          }}
        />
      )}
    </div>
  );
}

function WeekView({ groups, onGameClick, scheduleId }: {
  groups: [string, Game[]][];
  onGameClick: (g: Game) => void;
  scheduleId: string;
}) {
  return (
    <div className="space-y-4">
      {groups.map(([weekStart, games]) => {
        const weekDate = new Date(weekStart + 'T00:00:00');
        const label = weekDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        return (
          <div key={weekStart} className="card">
            <h3 className="text-sm font-semibold text-dark-400 mb-3">
              Week of {label} — <span className="text-primary-500">{games.length} games</span>
            </h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {games.sort((a, b) => a.game_date.localeCompare(b.game_date) || a.timeslot.localeCompare(b.timeslot))
                .map(g => <GameChip key={g.id} game={g} onClick={() => onGameClick(g)} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ListView({ games, onGameClick, scheduleId }: {
  games: Game[];
  onGameClick: (g: Game) => void;
  scheduleId: string;
}) {
  const sorted = [...games].sort((a, b) => a.game_date.localeCompare(b.game_date));
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-dark-700">
              {['Date', 'Time', 'Away Team', 'Home Team', 'Venue', 'Viewers', 'Type'].map(h => (
                <th key={h} className="text-left px-3 py-2.5 text-dark-500 font-medium text-xs uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-700">
            {sorted.map(g => {
              const home = TEAMS_BY_ID[g.home_team_id];
              const away = TEAMS_BY_ID[g.away_team_id];
              const venue = VENUES_BY_ID[g.venue_id];
              return (
                <tr
                  key={g.id}
                  onClick={() => onGameClick(g)}
                  className="hover:bg-dark-700/50 cursor-pointer transition-colors"
                >
                  <td className="px-3 py-2.5 text-dark-400 font-mono text-xs">{g.game_date}</td>
                  <td className="px-3 py-2.5 text-dark-500 text-xs whitespace-nowrap">{g.timeslot}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: away?.color }} />
                      <span className="text-white font-medium">{away?.name || g.away_team_id}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: home?.color }} />
                      <span className="text-white font-medium">{home?.name || g.home_team_id}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-dark-500 text-xs">{venue?.name || g.venue_id}</td>
                  <td className="px-3 py-2.5 text-dark-400 text-xs font-mono">
                    {g.projected_viewership ? `${(g.projected_viewership / 1000).toFixed(1)}K` : '—'}
                  </td>
                  <td className="px-3 py-2.5">
                    {g.is_rivalry ? (
                      <span className="px-2 py-0.5 bg-warning/20 text-warning text-xs rounded-full">⚡ Rivalry</span>
                    ) : (
                      <span className="text-dark-600 text-xs">Regular</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GameChip({ game, onClick }: { game: Game; onClick: () => void }) {
  const home = TEAMS_BY_ID[game.home_team_id];
  const away = TEAMS_BY_ID[game.away_team_id];
  const isPrimetime = ['Saturday 8', 'Sunday 4', 'Friday 7'].some(p => game.timeslot.includes(p));

  return (
    <button
      onClick={onClick}
      className={[
        'text-left p-3 rounded-lg border transition-all hover:scale-[1.02] active:scale-[0.99]',
        game.is_rivalry
          ? 'border-warning/40 bg-warning/5 hover:bg-warning/10'
          : isPrimetime
          ? 'border-primary-600/40 bg-primary-600/5 hover:bg-primary-600/10'
          : 'border-dark-700 bg-dark-700/30 hover:bg-dark-700',
      ].join(' ')}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-dark-500 font-mono">{game.game_date}</span>
        {game.is_rivalry && <span className="text-warning text-xs">⚡</span>}
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: away?.color }} />
          <span className="text-sm text-dark-400">{away?.name || game.away_team_id}</span>
        </div>
        <div className="text-dark-600 text-xs pl-3">at</div>
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: home?.color }} />
          <span className="text-sm text-white font-medium">{home?.name || game.home_team_id}</span>
        </div>
      </div>
      <div className="mt-2 text-xs text-dark-600">{game.timeslot}</div>
    </button>
  );
}

function StatCard({ label, value, icon }: { label: string; value: number; icon: string }) {
  return (
    <div className="card flex items-center gap-3">
      <span className="text-2xl">{icon}</span>
      <div>
        <p className="text-xs text-dark-600">{label}</p>
        <p className="font-bold text-white text-xl">{value}</p>
      </div>
    </div>
  );
}
