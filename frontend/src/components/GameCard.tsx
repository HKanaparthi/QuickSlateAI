import { useState, useEffect } from 'react';
import type { Game, Team, Venue } from '../types';
import { TEAMS_BY_ID, VENUES_BY_ID } from '../data/teams';

interface GameCardProps {
  game: Game;
  onClose: () => void;
  onExplain?: () => Promise<string>;
}

export default function GameCard({ game, onClose, onExplain }: GameCardProps) {
  const [explanation, setExplanation] = useState(game.ai_explanation || '');
  const [loadingExplanation, setLoadingExplanation] = useState(false);

  // Auto-fetch explanation if none pre-generated
  useEffect(() => {
    if (!game.ai_explanation && onExplain) {
      setLoadingExplanation(true);
      onExplain()
        .then(exp => setExplanation(exp))
        .finally(() => setLoadingExplanation(false));
    }
  }, [game.id]);

  const homeTeam = TEAMS_BY_ID[game.home_team_id];
  const awayTeam = TEAMS_BY_ID[game.away_team_id];
  const venue = VENUES_BY_ID[game.venue_id];

  const handleExplain = async () => {
    if (!onExplain) return;
    setLoadingExplanation(true);
    try {
      const exp = await onExplain();
      setExplanation(exp);
    } finally {
      setLoadingExplanation(false);
    }
  };

  const viewershipK = game.projected_viewership
    ? game.projected_viewership >= 1000
      ? `${(game.projected_viewership / 1000).toFixed(1)}K`
      : `${game.projected_viewership}`
    : null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-dark-800 border border-dark-700 rounded-xl shadow-2xl max-w-md w-full">
        {/* Header */}
        <div className="p-5 border-b border-dark-700 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              {game.is_rivalry && (
                <span className="px-2 py-0.5 bg-warning/20 text-warning text-xs font-medium rounded-full">
                  ⚡ Rivalry
                </span>
              )}
              <span className="px-2 py-0.5 bg-dark-700 text-dark-400 text-xs rounded-full">
                {game.timeslot}
              </span>
            </div>
            <h2 className="text-lg font-bold text-white mt-1">
              {awayTeam?.name || game.away_team_id}
            </h2>
            <p className="text-dark-500 text-sm">at</p>
            <h2 className="text-lg font-bold text-white">
              {homeTeam?.name || game.home_team_id}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-dark-500 hover:text-white transition-colors p-1"
          >
            ✕
          </button>
        </div>

        {/* Team Colors */}
        <div className="flex h-2">
          <div className="flex-1" style={{ backgroundColor: awayTeam?.color || '#6B7280' }} />
          <div className="flex-1" style={{ backgroundColor: homeTeam?.color || '#2563EB' }} />
        </div>

        {/* Details */}
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <DetailRow icon="📅" label="Date" value={game.game_date} />
            <DetailRow icon="🕐" label="Time" value={game.timeslot} />
            <DetailRow icon="🏟️" label="Venue" value={venue?.name || game.venue_id} />
            <DetailRow icon="📍" label="City" value={venue?.city || '—'} />
            {venue && (
              <DetailRow icon="👥" label="Capacity" value={`${venue.capacity.toLocaleString()}`} />
            )}
            {viewershipK && (
              <DetailRow icon="📺" label="Projected" value={`${viewershipK} viewers`} />
            )}
          </div>

          {/* AI Explanation */}
          <div className="mt-4 p-3 bg-dark-700 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-primary-500 uppercase tracking-wide">
                AI Scheduling Insight
              </span>
              {onExplain && (
                <button
                  onClick={handleExplain}
                  disabled={loadingExplanation}
                  className="text-xs text-primary-500 hover:text-primary-400 disabled:opacity-50"
                >
                  {loadingExplanation ? 'Loading...' : 'Refresh'}
                </button>
              )}
            </div>
            {loadingExplanation ? (
              <p className="text-sm text-dark-600 italic animate-pulse">Generating insight…</p>
            ) : explanation ? (
              <p className="text-sm text-dark-400 leading-relaxed">{explanation}</p>
            ) : (
              <p className="text-sm text-dark-600 italic">No insight available.</p>
            )}
          </div>
        </div>

        <div className="px-5 pb-5">
          <button onClick={onClose} className="btn-secondary w-full">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function DetailRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-base">{icon}</span>
      <div>
        <p className="text-dark-600 text-xs">{label}</p>
        <p className="text-white text-sm font-medium">{value}</p>
      </div>
    </div>
  );
}
