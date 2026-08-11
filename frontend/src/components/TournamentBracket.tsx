import { useState, useRef, useEffect } from 'react';
import * as d3 from 'd3';
import type { TournamentBracket, TournamentMatchup } from '../types';
import { generateTournament } from '../utils/api';
import { NPL_TEAMS, SAC_TEAMS, ALL_TEAMS } from '../data/teams';

const FORMATS = [
  { id: 'single_elimination', label: 'Single Elimination' },
  { id: 'round_robin', label: 'Round Robin' },
  { id: 'pool_play_knockout', label: 'Pool Play + Knockout' },
];

export default function TournamentBracket() {
  const [teamSource, setTeamSource] = useState<'NPL' | 'SAC' | 'custom'>('NPL');
  const [customTeams, setCustomTeams] = useState('');
  const [format, setFormat] = useState('single_elimination');
  const [numFields, setNumFields] = useState(2);
  const [pools, setPools] = useState(2);
  const [bracket, setBracket] = useState<TournamentBracket | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (bracket && svgRef.current && bracket.rounds) {
      drawBracket(bracket, svgRef.current);
    }
  }, [bracket]);

  const getTeamNames = () => {
    if (teamSource === 'NPL') return NPL_TEAMS.map(t => t.name);
    if (teamSource === 'SAC') return SAC_TEAMS.map(t => t.name);
    return customTeams.split('\n').map(t => t.trim()).filter(Boolean);
  };

  const generate = async () => {
    const names = getTeamNames();
    if (names.length < 2) {
      setError('Need at least 2 teams');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const result = await generateTournament({
        team_names: names,
        format,
        num_fields: numFields,
        pools,
        game_duration_minutes: 60,
        break_minutes: 15,
      });
      setBracket(result);
    } catch (e) {
      setError('Failed to generate bracket. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Setup Form */}
      <div className="card">
        <h3 className="section-title mb-4">Tournament Setup</h3>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="label">Team Source</label>
            <div className="flex gap-2">
              {(['NPL', 'SAC', 'custom'] as const).map(src => (
                <button
                  key={src}
                  type="button"
                  onClick={() => setTeamSource(src)}
                  className={[
                    'flex-1 py-2 px-3 rounded-lg border text-sm font-medium transition-all',
                    teamSource === src
                      ? 'bg-primary-600 border-primary-600 text-white'
                      : 'border-dark-600 text-dark-500 hover:border-primary-600 hover:text-white',
                  ].join(' ')}
                >
                  {src === 'custom' ? 'Custom' : src}
                </button>
              ))}
            </div>
            {teamSource === 'custom' && (
              <textarea
                className="input w-full mt-2"
                rows={6}
                placeholder="One team per line..."
                value={customTeams}
                onChange={e => setCustomTeams(e.target.value)}
              />
            )}
          </div>

          <div className="space-y-3">
            <div>
              <label className="label">Format</label>
              <select value={format} onChange={e => setFormat(e.target.value)} className="input w-full">
                {FORMATS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Fields/Courts</label>
                <input
                  type="number" min={1} max={8} value={numFields}
                  onChange={e => setNumFields(+e.target.value)}
                  className="input w-full"
                />
              </div>
              {format === 'pool_play_knockout' && (
                <div>
                  <label className="label">Number of Pools</label>
                  <input
                    type="number" min={2} max={8} value={pools}
                    onChange={e => setPools(+e.target.value)}
                    className="input w-full"
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        {error && <p className="text-danger text-sm mt-3">{error}</p>}

        <button
          onClick={generate}
          disabled={loading}
          className="btn-primary mt-4 w-full py-2.5 font-semibold disabled:opacity-60"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              Generating...
            </span>
          ) : (
            '🏆 Generate Bracket'
          )}
        </button>
      </div>

      {bracket && (
        <>
          {/* Bracket Visualization */}
          {bracket.rounds && (
            <div className="card overflow-x-auto">
              <h3 className="section-title mb-4">
                {FORMATS.find(f => f.id === bracket.format)?.label} Bracket
              </h3>
              <svg ref={svgRef} className="block mx-auto" />
            </div>
          )}

          {/* Round-by-Round list */}
          {bracket.rounds && (
            <RoundsList rounds={bracket.rounds} />
          )}

          {/* Pool Play */}
          {bracket.pool_stages && bracket.pool_stages.map((pool) => (
            <div key={pool.pool} className="card">
              <h3 className="section-title mb-3">{pool.pool} — Round Robin</h3>
              <RoundsList rounds={pool.schedule.rounds || []} compact />
            </div>
          ))}

          {/* Knockout Stage */}
          {bracket.knockout_stage?.rounds && (
            <div className="card">
              <h3 className="section-title mb-3">Knockout Stage</h3>
              <RoundsList rounds={bracket.knockout_stage.rounds} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RoundsList({ rounds, compact }: { rounds: TournamentBracket['rounds'] & any[]; compact?: boolean }) {
  return (
    <div className={`grid gap-4 ${compact ? 'grid-cols-2 md:grid-cols-3' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
      {rounds.map((round: any) => (
        <div key={round.round}>
          <h4 className="text-xs font-semibold text-dark-500 uppercase tracking-wider mb-2">
            {round.name}
          </h4>
          <div className="space-y-1.5">
            {round.matchups.map((m: TournamentMatchup) => (
              <MatchupCard key={m.id} matchup={m} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function MatchupCard({ matchup }: { matchup: TournamentMatchup }) {
  if (matchup.is_bye) {
    return (
      <div className="p-2.5 bg-dark-700/30 rounded-lg border border-dark-700 text-sm">
        <div className="text-white font-medium">{matchup.team1}</div>
        <div className="text-dark-600 text-xs mt-0.5">BYE — advances automatically</div>
        <div className="text-dark-600 text-xs mt-1">{matchup.field}</div>
      </div>
    );
  }
  return (
    <div className="p-2.5 bg-dark-700/50 rounded-lg border border-dark-700 text-sm hover:border-primary-600/40 transition-colors">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-primary-500" />
            <span className="text-white text-xs font-medium">{matchup.team1 || 'TBD'}</span>
          </div>
          <div className="text-dark-600 text-xs pl-3.5">vs</div>
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-dark-500" />
            <span className="text-dark-400 text-xs">{matchup.team2 || 'TBD'}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-dark-600">{matchup.field}</div>
          {matchup.winner && (
            <div className="text-xs text-success mt-1">✓ {matchup.winner}</div>
          )}
        </div>
      </div>
    </div>
  );
}

function drawBracket(bracket: TournamentBracket, svg: SVGSVGElement) {
  if (!bracket.rounds) return;
  const rounds = bracket.rounds;
  const CARD_W = 160, CARD_H = 60, H_GAP = 40, V_GAP = 20;
  const cols = rounds.length;
  const maxMatchups = Math.max(...rounds.map(r => r.matchups.length));
  const totalW = cols * (CARD_W + H_GAP);
  const totalH = maxMatchups * (CARD_H + V_GAP) + 40;

  d3.select(svg).selectAll('*').remove();
  d3.select(svg)
    .attr('width', totalW)
    .attr('height', totalH)
    .attr('viewBox', `0 0 ${totalW} ${totalH}`);

  const root = d3.select(svg).append('g').attr('transform', 'translate(0,20)');

  rounds.forEach((round, col) => {
    const nMatchups = round.matchups.length;
    const slotH = totalH / Math.max(nMatchups, 1);

    round.matchups.forEach((matchup: TournamentMatchup, row) => {
      const x = col * (CARD_W + H_GAP);
      const y = row * slotH + (slotH - CARD_H) / 2;

      const g = root.append('g').attr('transform', `translate(${x},${y})`);

      g.append('rect')
        .attr('width', CARD_W)
        .attr('height', CARD_H)
        .attr('rx', 6)
        .attr('fill', '#1e293b')
        .attr('stroke', '#334155')
        .attr('stroke-width', 1);

      g.append('line')
        .attr('x1', 0).attr('y1', CARD_H / 2)
        .attr('x2', CARD_W).attr('y2', CARD_H / 2)
        .attr('stroke', '#334155').attr('stroke-width', 1);

      g.append('text')
        .attr('x', 8).attr('y', CARD_H / 2 - 8)
        .attr('fill', '#e2e8f0').attr('font-size', '11')
        .text(matchup.team1 ? truncate(matchup.team1, 18) : 'TBD');

      g.append('text')
        .attr('x', 8).attr('y', CARD_H / 2 + 16)
        .attr('fill', '#94a3b8').attr('font-size', '11')
        .text(matchup.team2 ? truncate(matchup.team2, 18) : 'TBD');

      // Connector line
      if (col < rounds.length - 1) {
        const nextRound = rounds[col + 1];
        const nextSlotH = totalH / Math.max(nextRound.matchups.length, 1);
        const nextRow = Math.floor(row / 2);
        const nextY = nextRow * nextSlotH + (nextSlotH - CARD_H) / 2 + CARD_H / 2;
        const curY = y + CARD_H / 2;
        const midX = x + CARD_W + H_GAP / 2;

        root.append('path')
          .attr('d', `M ${x + CARD_W} ${curY} H ${midX} V ${nextY} H ${x + CARD_W + H_GAP}`)
          .attr('fill', 'none')
          .attr('stroke', '#334155')
          .attr('stroke-width', 1.5);
      }
    });

    root.append('text')
      .attr('x', col * (CARD_W + H_GAP) + CARD_W / 2)
      .attr('y', -8)
      .attr('text-anchor', 'middle')
      .attr('fill', '#64748b')
      .attr('font-size', '11')
      .attr('font-weight', '600')
      .text(round.name.toUpperCase());
  });
}

function truncate(s: string, max: number) {
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}
