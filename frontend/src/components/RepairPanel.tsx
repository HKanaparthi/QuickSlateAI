import { useState, useMemo } from 'react';
import type {
  Schedule, ValidationResult, ScheduleSummary, Game,
  RepairApiResponse, ComparisonMetrics, ComparisonMovedGame,
} from '../types';
import { TEAMS_BY_ID, VENUES_BY_ID } from '../data/teams';
import { repairSchedule, compareSchedules, getSchedule } from '../utils/api';

interface RepairPanelProps {
  schedule: Schedule;
  hasOriginal: boolean;
  onRepairAccepted: (repaired: Schedule, validation: ValidationResult, summary: ScheduleSummary) => void;
  onRestoreOriginal: () => void;
}

export default function RepairPanel({
  schedule,
  hasOriginal,
  onRepairAccepted,
  onRestoreOriginal,
}: RepairPanelProps) {
  // Form inputs
  const [venueId, setVenueId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [reason, setReason] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [neighborhoodSize, setNeighborhoodSize] = useState(5);
  const [maxExpansions, setMaxExpansions] = useState(3);
  const [timeLimit, setTimeLimit] = useState(30);

  // Result state
  const [isRepairing, setIsRepairing] = useState(false);
  const [repairResponse, setRepairResponse] = useState<RepairApiResponse | null>(null);
  const [repairedSchedule, setRepairedSchedule] = useState<Schedule | null>(null);
  const [repairedValidation, setRepairedValidation] = useState<ValidationResult | null>(null);
  const [repairedSummary, setRepairedSummary] = useState<ScheduleSummary | null>(null);
  const [comparison, setComparison] = useState<ComparisonMetrics | null>(null);
  const [formError, setFormError] = useState('');
  const [apiError, setApiError] = useState('');

  // Unique venues present in schedule
  const venueOptions = useMemo(() => {
    const ids = new Set(schedule.games.map(g => g.venue_id));
    return [...ids]
      .map(id => ({
        id,
        name: VENUES_BY_ID[id]?.name ?? id,
        city: VENUES_BY_ID[id]?.city ?? '',
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [schedule.games]);

  // Client-side affected game preview
  const affectedGames = useMemo((): Game[] => {
    if (!venueId || !startDate || !endDate) return [];
    return schedule.games.filter(
      g => g.venue_id === venueId && g.game_date >= startDate && g.game_date <= endDate
    );
  }, [schedule.games, venueId, startDate, endDate]);

  const validateForm = (): boolean => {
    if (!venueId) { setFormError('Select a venue.'); return false; }
    if (!startDate) { setFormError('Enter a blackout start date.'); return false; }
    if (!endDate) { setFormError('Enter a blackout end date.'); return false; }
    if (startDate > endDate) { setFormError('Start date must be on or before end date.'); return false; }
    setFormError('');
    return true;
  };

  const handleRunRepair = async () => {
    if (!validateForm()) return;
    setIsRepairing(true);
    setApiError('');
    setRepairResponse(null);
    setRepairedSchedule(null);
    setRepairedValidation(null);
    setRepairedSummary(null);
    setComparison(null);

    try {
      const result = await repairSchedule(schedule.id, {
        venue_id: venueId,
        blackout_start: startDate,
        blackout_end: endDate,
        reason: reason || undefined,
        neighborhood_size: neighborhoodSize,
        max_neighborhood_expansions: maxExpansions,
        time_limit_seconds: timeLimit,
      });
      setRepairResponse(result);

      if (
        result.repaired_schedule_id &&
        (result.status === 'REPAIR_OPTIMAL' || result.status === 'REPAIR_FEASIBLE')
      ) {
        try {
          const [schedData, cmpData] = await Promise.all([
            getSchedule(result.repaired_schedule_id),
            compareSchedules(schedule.id, result.repaired_schedule_id),
          ]);
          setRepairedSchedule(schedData.schedule);
          setRepairedValidation(schedData.validation);
          setRepairedSummary(schedData.summary);
          setComparison(cmpData);
        } catch {
          setRepairResponse(null);
          setApiError(
            'Repair succeeded but could not load repaired schedule details. ' +
            'The backend may have restarted. Try running the repair again.'
          );
        }
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setApiError(
        err?.response?.data?.detail ??
        'Repair request failed. Check that the backend is running on port 8000.'
      );
    } finally {
      setIsRepairing(false);
    }
  };

  const handleAccept = () => {
    if (repairedSchedule && repairedValidation && repairedSummary) {
      onRepairAccepted(repairedSchedule, repairedValidation, repairedSummary);
    }
  };

  const handleDiscard = () => {
    setRepairResponse(null);
    setRepairedSchedule(null);
    setRepairedValidation(null);
    setRepairedSummary(null);
    setComparison(null);
    setApiError('');
  };

  const inputsReady = venueId && startDate && endDate;

  return (
    <div className="space-y-5">
      {/* ── Blackout Input ─────────────────────────────────────────────── */}
      <div className="card">
        <h3 className="section-title mb-4">Venue Blackout</h3>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="label">Affected Venue</label>
            <select
              value={venueId}
              onChange={e => { setVenueId(e.target.value); setFormError(''); }}
              className="input w-full"
            >
              <option value="">Select a venue…</option>
              {venueOptions.map(v => (
                <option key={v.id} value={v.id}>
                  {v.name}{v.city ? ` · ${v.city}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Blackout Start</label>
            <input
              type="date"
              value={startDate}
              onChange={e => { setStartDate(e.target.value); setFormError(''); }}
              min={schedule.constraints.season_start}
              max={schedule.constraints.season_end}
              className="input w-full"
            />
          </div>

          <div>
            <label className="label">Blackout End</label>
            <input
              type="date"
              value={endDate}
              onChange={e => { setEndDate(e.target.value); setFormError(''); }}
              min={startDate || schedule.constraints.season_start}
              max={schedule.constraints.season_end}
              className="input w-full"
            />
          </div>

          <div className="sm:col-span-2">
            <label className="label">Reason (optional)</label>
            <input
              type="text"
              placeholder="e.g. Arena maintenance, conflicting event"
              value={reason}
              onChange={e => setReason(e.target.value)}
              className="input w-full"
            />
          </div>
        </div>

        {/* Advanced solver settings */}
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setShowAdvanced(v => !v)}
            className="text-xs text-dark-500 hover:text-dark-400 flex items-center gap-1 transition-colors"
          >
            <span>{showAdvanced ? '▾' : '▸'}</span> Advanced solver settings
          </button>
          {showAdvanced && (
            <div className="grid grid-cols-3 gap-4 mt-3 p-3 bg-dark-700/40 rounded-lg">
              <div>
                <label className="label">Neighborhood size</label>
                <input
                  type="number" min={1} max={20}
                  value={neighborhoodSize}
                  onChange={e => setNeighborhoodSize(Number(e.target.value))}
                  className="input w-full"
                />
                <p className="text-xs text-dark-600 mt-1">Games freed per pass</p>
              </div>
              <div>
                <label className="label">Max expansions</label>
                <input
                  type="number" min={0} max={5}
                  value={maxExpansions}
                  onChange={e => setMaxExpansions(Number(e.target.value))}
                  className="input w-full"
                />
                <p className="text-xs text-dark-600 mt-1">Retries on infeasibility</p>
              </div>
              <div>
                <label className="label">Time limit (s)</label>
                <input
                  type="number" min={5} max={120}
                  value={timeLimit}
                  onChange={e => setTimeLimit(Number(e.target.value))}
                  className="input w-full"
                />
                <p className="text-xs text-dark-600 mt-1">Per-stage budget</p>
              </div>
            </div>
          )}
        </div>

        {/* Affected games preview */}
        {inputsReady && (
          <div className="mt-4 pt-4 border-t border-dark-700">
            {affectedGames.length === 0 ? (
              <p className="text-xs text-dark-500">
                No games scheduled at this venue during the selected window.
              </p>
            ) : (
              <>
                <p className="text-xs font-medium text-dark-500 mb-2">
                  {affectedGames.length} game{affectedGames.length !== 1 ? 's' : ''} will require rescheduling:
                </p>
                <div className="space-y-1.5">
                  {affectedGames.map(g => {
                    const home = TEAMS_BY_ID[g.home_team_id];
                    const away = TEAMS_BY_ID[g.away_team_id];
                    return (
                      <div
                        key={g.id}
                        className="flex items-center gap-3 p-2.5 bg-warning/10 border border-warning/25 rounded-lg text-xs"
                      >
                        <span className="text-warning flex-shrink-0">◉</span>
                        <span className="text-white font-medium">
                          {home?.name ?? g.home_team_id} vs {away?.name ?? g.away_team_id}
                        </span>
                        <span className="text-dark-500 ml-auto whitespace-nowrap">
                          {g.game_date} · {g.timeslot}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}

        {formError && (
          <p className="mt-3 text-xs text-danger">{formError}</p>
        )}

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleRunRepair}
            disabled={isRepairing}
            className="btn-primary"
          >
            {isRepairing ? 'Repairing…' : 'Run Repair →'}
          </button>
          {inputsReady && affectedGames.length === 0 && (
            <span className="text-xs text-dark-500">No affected games — repair will confirm nothing to reschedule.</span>
          )}
        </div>
      </div>

      {/* ── Loading ────────────────────────────────────────────────────── */}
      {isRepairing && (
        <div className="card flex items-center gap-4">
          <div className="w-8 h-8 border-[3px] border-primary-600 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <div>
            <p className="text-white text-sm font-medium">Running CP-SAT repair solver…</p>
            <p className="text-dark-500 text-xs mt-0.5">
              Sequential lexicographic optimization: minimize moves → displacement → maximize quality
            </p>
          </div>
        </div>
      )}

      {/* ── API Error ─────────────────────────────────────────────────── */}
      {apiError && !isRepairing && (
        <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
          {apiError}
        </div>
      )}

      {/* ── Repair Result ─────────────────────────────────────────────── */}
      {repairResponse && !isRepairing && (
        <RepairResultPanel
          response={repairResponse}
          comparison={comparison}
          repairedSchedule={repairedSchedule}
          onAccept={handleAccept}
          onDiscard={handleDiscard}
        />
      )}

      {/* ── Restore Original ──────────────────────────────────────────── */}
      {hasOriginal && (
        <div className="card border-dark-600">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-white">Original Schedule Preserved</p>
              <p className="text-xs text-dark-500 mt-0.5">
                The pre-repair schedule is still stored. You can revert at any time.
              </p>
            </div>
            <button
              type="button"
              onClick={onRestoreOriginal}
              className="btn-secondary text-sm flex-shrink-0"
            >
              ← Restore Original
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

interface RepairResultPanelProps {
  response: RepairApiResponse;
  comparison: ComparisonMetrics | null;
  repairedSchedule: Schedule | null;
  onAccept: () => void;
  onDiscard: () => void;
}

type StatusConfig = { label: string; color: string; bg: string; icon: string };

const STATUS_CONFIG: Record<string, StatusConfig> = {
  REPAIR_OPTIMAL: {
    label: 'Optimal',
    color: 'text-success',
    bg: 'bg-success/10 border-success/30',
    icon: '✓',
  },
  REPAIR_FEASIBLE: {
    label: 'Feasible',
    color: 'text-warning',
    bg: 'bg-warning/10 border-warning/30',
    icon: '◐',
  },
  NO_GAMES_AFFECTED: {
    label: 'No Action Needed',
    color: 'text-primary-500',
    bg: 'bg-primary-500/10 border-primary-500/30',
    icon: 'ℹ',
  },
  REPAIR_TIMEOUT_NO_SOLUTION: {
    label: 'Timeout — No Solution Found',
    color: 'text-warning',
    bg: 'bg-warning/10 border-warning/30',
    icon: '⏱',
  },
  REPAIR_GLOBALLY_INFEASIBLE_IN_BUDGET: {
    label: 'Search Limit Reached',
    color: 'text-danger',
    bg: 'bg-danger/10 border-danger/30',
    icon: '✗',
  },
  REPAIR_NEIGHBORHOOD_INFEASIBLE: {
    label: 'Infeasible in Neighborhood',
    color: 'text-danger',
    bg: 'bg-danger/10 border-danger/30',
    icon: '✗',
  },
  REPAIR_VALIDATION_FAILED: {
    label: 'Validation Failed',
    color: 'text-danger',
    bg: 'bg-danger/10 border-danger/30',
    icon: '✗',
  },
};

function RepairResultPanel({
  response,
  comparison,
  repairedSchedule,
  onAccept,
  onDiscard,
}: RepairResultPanelProps) {
  const cfg: StatusConfig = STATUS_CONFIG[response.status] ?? {
    label: response.status,
    color: 'text-dark-400',
    bg: 'bg-dark-700 border-dark-600',
    icon: '?',
  };
  const isSuccess =
    response.status === 'REPAIR_OPTIMAL' || response.status === 'REPAIR_FEASIBLE';

  return (
    <div className="card space-y-4">
      <h3 className="section-title">Repair Result</h3>

      {/* Status badge */}
      <div className={`flex items-center gap-3 p-3 rounded-lg border ${cfg.bg}`}>
        <span className={`text-base font-bold leading-none ${cfg.color}`}>{cfg.icon}</span>
        <div className="min-w-0">
          <span className={`font-semibold text-sm ${cfg.color}`}>{cfg.label}</span>
          {response.solve_time_seconds !== undefined && (
            <span className="ml-3 text-xs text-dark-500">
              {response.solve_time_seconds.toFixed(2)}s
              {(response.neighborhood_expansions_used ?? 0) > 0 &&
                ` · ${response.neighborhood_expansions_used} expansion${response.neighborhood_expansions_used !== 1 ? 's' : ''}`}
              {response.objective_gap != null &&
                ` · gap ${(response.objective_gap * 100).toFixed(1)}%`}
            </span>
          )}
        </div>
      </div>

      {/* Error or info message */}
      {(response.error_message || response.message) && (
        <p className="text-xs text-dark-400 px-1 leading-relaxed">
          {response.error_message ?? response.message}
        </p>
      )}

      {/* Validation summary */}
      {response.validation_result && (
        <ValidationSummary validation={response.validation_result} />
      )}

      {/* Before/After comparison */}
      {isSuccess && comparison && (
        <ComparisonView comparison={comparison} />
      )}

      {/* Action buttons */}
      {isSuccess && repairedSchedule ? (
        <div className="flex items-center gap-3 pt-2 border-t border-dark-700">
          <button type="button" onClick={onAccept} className="btn-primary">
            Accept Repair
          </button>
          <button type="button" onClick={onDiscard} className="btn-secondary">
            Discard
          </button>
          <span className="text-xs text-dark-600 ml-auto font-mono">
            {response.repaired_schedule_id?.slice(0, 8)}…
          </span>
        </div>
      ) : (
        !isSuccess && (
          <div className="pt-2 border-t border-dark-700">
            <button type="button" onClick={onDiscard} className="btn-secondary text-sm">
              {response.status === 'NO_GAMES_AFFECTED' ? 'Done' : 'Try Different Settings'}
            </button>
          </div>
        )
      )}
    </div>
  );
}

function ValidationSummary({ validation }: { validation: NonNullable<RepairApiResponse['validation_result']> }) {
  const statusColor = {
    RED: 'text-danger',
    YELLOW: 'text-warning',
    GREEN: 'text-success',
  };
  const statusIcon = { RED: '🔴', YELLOW: '⚠️', GREEN: '✅' };
  const st = validation.status as 'RED' | 'YELLOW' | 'GREEN';
  return (
    <div className="flex items-center gap-3 p-3 bg-dark-700/60 rounded-lg text-sm">
      <span>{statusIcon[st] ?? '?'}</span>
      <span className={`font-medium ${statusColor[st] ?? 'text-dark-400'}`}>
        Validation: {st === 'GREEN' ? 'All Clear' : `${validation.red_count} critical, ${validation.yellow_count} warning${validation.yellow_count !== 1 ? 's' : ''}`}
      </span>
    </div>
  );
}

function ComparisonView({ comparison }: { comparison: ComparisonMetrics }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-dark-400 uppercase tracking-wider mb-3">
        Before → After
      </h4>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 gap-3 mb-4 sm:grid-cols-4">
        <MetricPill label="Moved" value={String(comparison.games_moved)} />
        <MetricPill label="Unchanged" value={String(comparison.games_unchanged)} />
        <MetricPill
          label="Total Displacement"
          value={`${comparison.total_displacement_days}d`}
        />
        {comparison.quality_delta !== 0 && (
          <MetricPill
            label="Objective Δ"
            value={(comparison.quality_delta >= 0 ? '+' : '') + comparison.quality_delta}
            highlight={comparison.quality_delta > 0 ? 'green' : 'red'}
          />
        )}
      </div>

      {/* Moved games list */}
      {comparison.moved_games.length > 0 && (
        <div className="space-y-2">
          {comparison.moved_games.map(m => (
            <MovedGameRow key={m.game_id} move={m} />
          ))}
        </div>
      )}
    </div>
  );
}

function MovedGameRow({ move }: { move: ComparisonMovedGame }) {
  const home = TEAMS_BY_ID[move.home_team_id];
  const away = TEAMS_BY_ID[move.away_team_id];
  return (
    <div className="p-3 bg-dark-700 rounded-lg text-xs space-y-2">
      <p className="text-sm font-medium text-white">
        {home?.name ?? move.home_team_id} vs {away?.name ?? move.away_team_id}
      </p>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-danger/90 line-through">
          {move.original_date} · {move.original_timeslot}
        </span>
        <span className="text-dark-500">→</span>
        <span className="text-success">
          {move.repaired_date} · {move.repaired_timeslot}
        </span>
        <span className="ml-auto text-dark-500 whitespace-nowrap">
          {move.displacement_days} day{move.displacement_days !== 1 ? 's' : ''}
        </span>
      </div>
    </div>
  );
}

function MetricPill({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: 'green' | 'red';
}) {
  const valueColor = highlight === 'green'
    ? 'text-success'
    : highlight === 'red'
    ? 'text-danger'
    : 'text-white';
  return (
    <div className="bg-dark-700 rounded-lg p-2.5 text-center">
      <p className={`font-bold text-lg font-mono ${valueColor}`}>{value}</p>
      <p className="text-xs text-dark-500 mt-0.5">{label}</p>
    </div>
  );
}
