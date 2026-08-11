import { useState, useMemo } from 'react';
import type { Schedule, ValidationResult, Violation } from '../types';
import { TEAMS_BY_ID, VENUES_BY_ID } from '../data/teams';
import { updateGame } from '../utils/api';

interface ConflictDashboardProps {
  schedule: Schedule;
  validation: ValidationResult;
  onScheduleUpdate: (updatedSchedule: Schedule, newValidation: ValidationResult) => void;
}

const TIMESLOTS = [
  'Saturday 8:00 PM', 'Sunday 4:00 PM', 'Friday 7:00 PM',
  'Monday 7:00 PM', 'Tuesday 6:00 PM', 'Wednesday 7:00 PM', 'Thursday 7:00 PM',
];

export default function ConflictDashboard({ schedule, validation, onScheduleUpdate }: ConflictDashboardProps) {
  const [filterType, setFilterType] = useState('ALL');
  const [filterTeam, setFilterTeam] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('ALL');
  const [editingGame, setEditingGame] = useState<string | null>(null);
  const [editDate, setEditDate] = useState('');
  const [editSlot, setEditSlot] = useState('');
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<Array<{ schedule: Schedule; validation: ValidationResult }>>([]);

  const allTeams = useMemo(() => {
    const ids = new Set<string>();
    schedule.games.forEach(g => { ids.add(g.home_team_id); ids.add(g.away_team_id); });
    return [...ids].map(id => TEAMS_BY_ID[id]).filter(Boolean);
  }, [schedule]);

  const filteredViolations = useMemo(() => {
    return validation.violations.filter(v => {
      if (filterSeverity !== 'ALL' && v.severity !== filterSeverity) return false;
      if (filterType !== 'ALL' && v.type !== filterType) return false;
      if (filterTeam && v.team_id !== filterTeam) return false;
      return true;
    });
  }, [validation.violations, filterSeverity, filterType, filterTeam]);

  const violationTypes = useMemo(() => {
    const types = new Set(validation.violations.map(v => v.type));
    return [...types];
  }, [validation.violations]);

  const startEdit = (gameId: string) => {
    const game = schedule.games.find(g => g.id === gameId);
    if (!game) return;
    setEditingGame(gameId);
    setEditDate(game.game_date);
    setEditSlot(game.timeslot);
  };

  const saveEdit = async () => {
    if (!editingGame) return;
    setSaving(true);
    try {
      setHistory(prev => [...prev, { schedule, validation }]);
      const res = await updateGame(schedule.id, editingGame, editDate, editSlot);
      const updatedGames = schedule.games.map(g =>
        g.id === editingGame ? res.updated_game : g
      );
      onScheduleUpdate({ ...schedule, games: updatedGames }, res.validation);
      setEditingGame(null);
    } catch (err) {
      console.error('Failed to update game', err);
    } finally {
      setSaving(false);
    }
  };

  const undo = () => {
    if (history.length === 0) return;
    const prev = history[history.length - 1];
    onScheduleUpdate(prev.schedule, prev.validation);
    setHistory(h => h.slice(0, -1));
  };

  const statusStyles: Record<string, string> = {
    RED: 'bg-danger/10 border-danger/30 text-danger',
    YELLOW: 'bg-warning/10 border-warning/30 text-warning',
    GREEN: 'bg-success/10 border-success/30 text-success',
  };

  const overallStatus = validation.status;

  return (
    <div className="space-y-5">
      {/* Status Overview */}
      <div className="grid grid-cols-3 gap-4">
        <StatusCard label="Critical Conflicts" count={validation.red_count} severity="RED" icon="🔴" />
        <StatusCard label="Warnings" count={validation.yellow_count} severity="YELLOW" icon="⚠️" />
        <StatusCard
          label="Schedule Health"
          count={overallStatus === 'GREEN' ? 1 : 0}
          severity={overallStatus}
          icon={overallStatus === 'GREEN' ? '✅' : overallStatus === 'YELLOW' ? '⚠️' : '🚨'}
          isStatus
          statusText={overallStatus === 'GREEN' ? 'All Clear' : overallStatus === 'YELLOW' ? 'Warnings' : 'Critical Issues'}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={undo}
          disabled={history.length === 0}
          className="btn-secondary text-sm disabled:opacity-40"
        >
          ↩ Undo
        </button>
        <span className="text-dark-600 text-sm">{history.length} change{history.length !== 1 ? 's' : ''} tracked</span>
      </div>

      {/* Filters */}
      <div className="card">
        <h3 className="section-title mb-3">Filter Violations</h3>
        <div className="flex flex-wrap gap-3">
          <select value={filterSeverity} onChange={e => setFilterSeverity(e.target.value)} className="input text-sm">
            <option value="ALL">All Severities</option>
            <option value="RED">Critical (RED)</option>
            <option value="YELLOW">Warning (YELLOW)</option>
          </select>
          <select value={filterType} onChange={e => setFilterType(e.target.value)} className="input text-sm">
            <option value="ALL">All Types</option>
            {violationTypes.map(t => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <select value={filterTeam} onChange={e => setFilterTeam(e.target.value)} className="input text-sm">
            <option value="">All Teams</option>
            {allTeams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
      </div>

      {/* Violations List */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="section-title">
            Violations ({filteredViolations.length})
          </h3>
        </div>

        {filteredViolations.length === 0 ? (
          <div className="text-center py-10 text-dark-600">
            <div className="text-4xl mb-3">
              {overallStatus === 'GREEN' ? '✅' : '🔍'}
            </div>
            <p>{overallStatus === 'GREEN' ? 'No violations detected — schedule is clean!' : 'No violations match current filters.'}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredViolations.map((v, i) => (
              <ViolationRow
                key={i}
                violation={v}
                schedule={schedule}
                onEditGame={startEdit}
              />
            ))}
          </div>
        )}
      </div>

      {/* Game Editor */}
      {editingGame && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 border border-dark-700 rounded-xl shadow-2xl max-w-sm w-full p-6">
            <h3 className="text-white font-bold mb-4">Reschedule Game</h3>
            {(() => {
              const game = schedule.games.find(g => g.id === editingGame);
              const home = game ? TEAMS_BY_ID[game.home_team_id] : null;
              const away = game ? TEAMS_BY_ID[game.away_team_id] : null;
              return game ? (
                <p className="text-dark-400 text-sm mb-4">
                  {away?.name} at {home?.name}
                </p>
              ) : null;
            })()}
            <div className="space-y-3 mb-5">
              <div>
                <label className="label">New Date</label>
                <input
                  type="date"
                  value={editDate}
                  onChange={e => setEditDate(e.target.value)}
                  className="input w-full"
                />
              </div>
              <div>
                <label className="label">New Time Slot</label>
                <select value={editSlot} onChange={e => setEditSlot(e.target.value)} className="input w-full">
                  {TIMESLOTS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => setEditingGame(null)}
                className="btn-secondary flex-1"
                disabled={saving}
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={saving}
                className="btn-primary flex-1 disabled:opacity-60"
              >
                {saving ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusCard({ label, count, severity, icon, isStatus, statusText }: {
  label: string; count: number; severity: string; icon: string; isStatus?: boolean; statusText?: string;
}) {
  const colors: Record<string, string> = {
    RED: 'border-danger/30 bg-danger/5',
    YELLOW: 'border-warning/30 bg-warning/5',
    GREEN: 'border-success/30 bg-success/5',
  };
  const textColors: Record<string, string> = {
    RED: 'text-danger', YELLOW: 'text-warning', GREEN: 'text-success',
  };
  return (
    <div className={`card border ${colors[severity] || 'border-dark-700'} flex items-center gap-3`}>
      <span className="text-2xl">{icon}</span>
      <div>
        <p className="text-xs text-dark-600">{label}</p>
        <p className={`font-bold text-lg ${textColors[severity]}`}>
          {isStatus ? statusText : count}
        </p>
      </div>
    </div>
  );
}

function ViolationRow({ violation, schedule, onEditGame }: {
  violation: Violation;
  schedule: Schedule;
  onEditGame: (gameId: string) => void;
}) {
  const team = violation.team_id ? TEAMS_BY_ID[violation.team_id] : null;
  const relatedGame = violation.game1_id
    ? schedule.games.find(g => g.id === violation.game1_id)
    : null;

  const borderColors: Record<string, string> = {
    RED: 'border-danger/30',
    YELLOW: 'border-warning/30',
    GREEN: 'border-success/30',
  };
  const dotColors: Record<string, string> = {
    RED: 'bg-danger', YELLOW: 'bg-warning', GREEN: 'bg-success',
  };

  return (
    <div className={`p-3 rounded-lg border ${borderColors[violation.severity] || 'border-dark-700'} flex items-start justify-between gap-3`}>
      <div className="flex items-start gap-3">
        <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${dotColors[violation.severity]}`} />
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-xs font-medium text-dark-500 uppercase">
              {violation.type.replace(/_/g, ' ')}
            </span>
            {team && (
              <span className="text-xs text-dark-600">• {team.name}</span>
            )}
          </div>
          <p className="text-sm text-dark-400">{violation.message}</p>
        </div>
      </div>
      {relatedGame && (
        <button
          onClick={() => onEditGame(relatedGame.id)}
          className="text-xs text-primary-500 hover:text-primary-400 whitespace-nowrap"
        >
          Reschedule
        </button>
      )}
    </div>
  );
}
