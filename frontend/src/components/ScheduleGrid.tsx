import { useState, useMemo } from 'react';
import type { Game, Schedule, ValidationResult, ScheduleSummary, FeasibilityAnalysis, SolverMetrics } from '../types';
import { TEAMS_BY_ID, VENUES_BY_ID } from '../data/teams';
import GameCard from './GameCard';
import { explainGame } from '../utils/api';

interface ScheduleGridProps {
  schedule: Schedule;
  validation: ValidationResult;
  summary: ScheduleSummary;
  feasibilityAnalysis?: FeasibilityAnalysis;
  solverMetrics?: SolverMetrics;
}

export default function ScheduleGrid({ schedule, validation, summary, feasibilityAnalysis, solverMetrics }: ScheduleGridProps) {
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

      {/* Feasibility / Conflict Analysis */}
      {feasibilityAnalysis && (feasibilityAnalysis.issues.length > 0 || feasibilityAnalysis.warnings.length > 0) && (
        <div className="card border-warning/30">
          <h3 className="text-sm font-semibold text-warning mb-3">Constraint Analysis</h3>
          {feasibilityAnalysis.issues.map((issue, i) => (
            <div key={i} className="mb-2 p-3 bg-danger/10 border border-danger/20 rounded-lg">
              <div className="flex items-start gap-2">
                <span className="text-danger text-sm mt-0.5">●</span>
                <div>
                  <p className="text-sm text-white">{issue.message}</p>
                  {issue.suggestion && (
                    <p className="text-xs text-dark-500 mt-1">Suggestion: {issue.suggestion}</p>
                  )}
                </div>
              </div>
            </div>
          ))}
          {feasibilityAnalysis.warnings.map((w, i) => (
            <div key={i} className="mb-2 p-3 bg-warning/10 border border-warning/20 rounded-lg">
              <div className="flex items-start gap-2">
                <span className="text-warning text-sm mt-0.5">▲</span>
                <p className="text-sm text-dark-400">{w}</p>
              </div>
            </div>
          ))}
          <div className="mt-3 pt-3 border-t border-dark-700 grid grid-cols-3 gap-3 text-center text-xs text-dark-500">
            <div><span className="block text-white font-mono text-lg">{feasibilityAnalysis.total_games}</span>total games</div>
            <div><span className="block text-white font-mono text-lg">{feasibilityAnalysis.available_slots}</span>available slots</div>
            <div><span className="block text-white font-mono text-lg">{feasibilityAnalysis.games_per_team}</span>games/team</div>
          </div>
        </div>
      )}

      {/* Broadcast Compliance */}
      {validation.broadcast_compliance && validation.broadcast_compliance.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-white mb-3">Broadcast Compliance</h3>
          <div className="space-y-2">
            {validation.broadcast_compliance.map((item, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-dark-700 last:border-0">
                <div className="flex items-center gap-3">
                  <span className={[
                    'w-2 h-2 rounded-full flex-shrink-0',
                    item.status === 'OK' ? 'bg-success' : item.status === 'OVER' ? 'bg-warning' : 'bg-danger',
                  ].join(' ')} />
                  <div>
                    <span className="text-sm font-semibold text-white">{item.network}</span>
                    <span className="ml-2 text-xs text-dark-500">{item.timeslot}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-dark-500">Required: <span className="text-dark-300">{item.required}</span></span>
                  <span className="text-dark-500">Max: <span className="text-dark-300">{item.max}</span></span>
                  <span className={[
                    'font-semibold px-2 py-0.5 rounded',
                    item.status === 'OK' ? 'text-success bg-success/10' : item.status === 'OVER' ? 'text-warning bg-warning/10' : 'text-danger bg-danger/10',
                  ].join(' ')}>
                    {item.actual} {item.status === 'OK' ? '✓' : item.status === 'OVER' ? '▲' : '✗'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Infeasibility Explainer */}
      {(schedule.solver_status === 'INFEASIBLE' || schedule.solver_status === 'TIMEOUT_FALLBACK') && (
        <div className="card border-danger/40 bg-danger/5">
          <h3 className="text-sm font-semibold text-danger mb-3">
            {schedule.solver_status === 'INFEASIBLE' ? 'Schedule Infeasible — No Valid Solution Found' : 'Solver Timeout — Greedy Fallback Applied'}
          </h3>
          <p className="text-xs text-dark-500 mb-3">
            {schedule.solver_status === 'INFEASIBLE'
              ? 'OR-Tools CP-SAT proved no schedule satisfies all hard constraints simultaneously. The greedy fallback below violates some constraints. Diagnosis:'
              : 'The solver hit its 30-second time limit before finding an optimal solution. The greedy fallback may not satisfy all constraints.'}
          </p>
          {solverMetrics?.infeasibility_reasons && solverMetrics.infeasibility_reasons.length > 0 && (
            <div className="space-y-2 mb-4">
              {solverMetrics.infeasibility_reasons.map((reason, i) => (
                <div key={i} className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-lg">
                  <span className="text-danger mt-0.5 flex-shrink-0">●</span>
                  <p className="text-xs text-dark-300">{reason}</p>
                </div>
              ))}
            </div>
          )}
          <div className="text-xs text-dark-500 p-3 bg-dark-700/60 rounded-lg">
            <span className="text-warning font-semibold">Possible relaxations: </span>
            Reduce min_rest_days · Extend season end date · Lower broadcaster required_games · Shorten venue blackout windows · Lower target_games_per_week
          </div>
        </div>
      )}

      {/* Constraint Audit Panel */}
      {solverMetrics && schedule.solver_status !== 'GREEDY_FALLBACK' && (
        <ConstraintAuditPanel metrics={solverMetrics} />
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

function ConstraintAuditPanel({ metrics }: { metrics: SolverMetrics }) {
  const isOptimal = metrics.solver_status === 'OPTIMAL';
  const isFeasible = metrics.solver_status === 'FEASIBLE';
  const solved = isOptimal || isFeasible;

  const auditRows = [
    {
      label: 'Hard constraints satisfied',
      value: solved ? `All ${metrics.hard_constraints_count.toLocaleString()}` : 'Not all',
      pass: solved,
      detail: `${metrics.n_matchups} matchups × ${metrics.n_slots} slots`,
    },
    {
      label: 'Venue conflicts',
      value: metrics.venue_conflicts === 0 ? '0 ✓' : `${metrics.venue_conflicts} violations`,
      pass: metrics.venue_conflicts === 0,
      detail: 'No double-booked venue/timeslot pairs',
    },
    {
      label: 'Rest day violations',
      value: metrics.rest_violations === 0 ? '0 ✓' : `${metrics.rest_violations} violations`,
      pass: metrics.rest_violations === 0,
      detail: 'Minimum rest days enforced by solver',
    },
    {
      label: 'Broadcaster commitments',
      value: metrics.broadcaster_total > 0
        ? `${metrics.broadcaster_satisfied}/${metrics.broadcaster_total} contracts ✓`
        : 'No contracts configured',
      pass: metrics.broadcaster_total === 0 || metrics.broadcaster_satisfied === metrics.broadcaster_total,
      detail: 'Required game counts per timeslot',
    },
    {
      label: 'Home/away imbalance teams',
      value: metrics.home_away_imbalance_count === 0 ? '0 ✓' : `${metrics.home_away_imbalance_count} teams flagged`,
      pass: metrics.home_away_imbalance_count === 0,
      detail: '>15% deviation from 50/50 split',
    },
    {
      label: 'Back-to-back away (post-repair)',
      value: metrics.back_to_back_away_count === 0 ? '0 remaining ✓' : `${metrics.back_to_back_away_count} remaining`,
      pass: metrics.back_to_back_away_count === 0,
      detail: 'Greedy repair pass applied after solve',
    },
  ];

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">Constraint Audit</h3>
          <p className="text-xs text-dark-600 mt-0.5">
            {metrics.cba_profile_applied ? `CBA Profile: ${metrics.cba_profile_applied} · ` : ''}
            OR-Tools CP-SAT · Status: <span className={isOptimal ? 'text-success' : isFeasible ? 'text-warning' : 'text-danger'}>{metrics.solver_status}</span>
          </p>
        </div>
        <div className="text-right text-xs text-dark-600">
          <div className="font-mono text-white">{metrics.decisions_evaluated.toLocaleString()}</div>
          <div>decisions evaluated</div>
        </div>
      </div>

      <div className="space-y-2">
        {auditRows.map((row, i) => (
          <div key={i} className="flex items-center justify-between py-2 border-b border-dark-700 last:border-0">
            <div className="flex items-center gap-2">
              <span className={row.pass ? 'text-success' : 'text-warning'}>
                {row.pass ? '✓' : '~'}
              </span>
              <div>
                <span className="text-sm text-dark-300">{row.label}</span>
                <span className="text-xs text-dark-600 ml-2 hidden sm:inline">{row.detail}</span>
              </div>
            </div>
            <span className={`text-xs font-mono font-semibold ${row.pass ? 'text-success' : 'text-warning'}`}>
              {row.value}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-dark-700 grid grid-cols-3 gap-3 text-center text-xs text-dark-500">
        <div>
          <span className="block text-white font-mono">{metrics.solve_time_seconds}s</span>
          solve time
        </div>
        <div>
          <span className="block text-white font-mono">{metrics.total_variables.toLocaleString()}</span>
          decision variables
        </div>
        <div>
          <span className="block text-white font-mono">{metrics.objective_value?.toLocaleString() ?? '—'}</span>
          objective score
        </div>
      </div>
    </div>
  );
}
