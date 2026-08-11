import { useEffect, useState, useRef } from 'react';
import * as d3 from 'd3';
import type { AudienceAnalysis, GameAudienceEstimate } from '../types';
import { getAudienceAnalysis } from '../utils/api';

interface AudienceEstimatorProps {
  scheduleId: string;
}

export default function AudienceEstimator({ scheduleId }: AudienceEstimatorProps) {
  const [analysis, setAnalysis] = useState<AudienceAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedGame, setSelectedGame] = useState<GameAudienceEstimate | null>(null);
  const chartRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    getAudienceAnalysis(scheduleId)
      .then(setAnalysis)
      .catch(() => setError('Failed to load audience analysis'))
      .finally(() => setLoading(false));
  }, [scheduleId]);

  useEffect(() => {
    if (!analysis || !chartRef.current) return;
    drawChart(analysis.game_estimates, chartRef.current);
  }, [analysis]);

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="card text-danger p-6">{error}</div>;
  if (!analysis) return null;

  const totalM = (analysis.total_projected_viewership / 1_000_000).toFixed(1);
  const avgK = (analysis.avg_viewership_per_game / 1000).toFixed(1);

  return (
    <div className="space-y-5">
      {/* Summary */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MiniStat label="Total Projected" value={`${totalM}M`} sub="viewers" />
        <MiniStat label="Avg Per Game" value={`${avgK}K`} sub="viewers" />
        <MiniStat label="Total Games" value={analysis.game_estimates.length.toString()} sub="scheduled" />
        <MiniStat
          label="Peak Game"
          value={analysis.peak_games[0] ? `${(analysis.peak_games[0].projected_viewership / 1000).toFixed(0)}K` : '—'}
          sub={analysis.peak_games[0] ? `${analysis.peak_games[0].home_team} home` : ''}
        />
      </div>

      {/* Viewership Line Chart */}
      <div className="card">
        <h3 className="section-title mb-4">Season Viewership Projection</h3>
        <svg ref={chartRef} className="w-full" style={{ height: '260px' }} />
        <p className="text-xs text-dark-600 mt-2">Click any point to see game details</p>
      </div>

      {/* Selected Game Breakdown */}
      {selectedGame && (
        <div className="card border border-primary-600/30">
          <h3 className="section-title mb-3">Game Breakdown</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-white font-medium">{selectedGame.away_team} at {selectedGame.home_team}</p>
              <p className="text-dark-500 text-sm">{selectedGame.game_date} · {selectedGame.timeslot}</p>
              {selectedGame.is_rivalry && (
                <span className="inline-block mt-1 px-2 py-0.5 bg-warning/20 text-warning text-xs rounded-full">⚡ Rivalry</span>
              )}
            </div>
            <div className="text-right">
              <p className="text-3xl font-bold text-white">
                {(selectedGame.projected_viewership / 1000).toFixed(0)}K
              </p>
              <p className="text-dark-500 text-xs">projected viewers</p>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {Object.entries(selectedGame.factor_contributions).map(([key, val]) => (
              <div key={key} className="bg-dark-700 rounded-lg p-3 text-center">
                <p className="text-xs text-dark-500 capitalize">{key.replace(/_/g, ' ')}</p>
                <p className={`font-bold text-sm mt-1 ${val.startsWith('+') ? 'text-success' : val === '0%' ? 'text-dark-500' : 'text-danger'}`}>
                  {val}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Timeslot Analysis */}
      <div className="card">
        <h3 className="section-title mb-4">Timeslot Performance</h3>
        <div className="space-y-2">
          {Object.entries(analysis.timeslot_analysis)
            .sort(([, a], [, b]) => b.avg - a.avg)
            .map(([slot, data]) => {
              const maxAvg = Math.max(...Object.values(analysis.timeslot_analysis).map(d => d.avg));
              const barPct = (data.avg / maxAvg) * 100;
              return (
                <div key={slot} className="flex items-center gap-3">
                  <span className="text-sm text-dark-400 w-36 flex-shrink-0 text-right">{slot}</span>
                  <div className="flex-1 h-5 bg-dark-700 rounded overflow-hidden">
                    <div
                      className="h-full bg-primary-600 rounded transition-all"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <span className="text-xs text-dark-500 w-20">
                    {(data.avg / 1000).toFixed(1)}K avg
                  </span>
                  <span className="text-xs text-dark-600 w-14">{data.count} games</span>
                </div>
              );
            })}
        </div>
      </div>

      {/* Top & Low Games */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <GameList title="Peak Games" games={analysis.peak_games} accent="text-success" icon="🔥" />
        <GameList title="Low Viewership" games={analysis.low_games} accent="text-dark-500" icon="📉" />
      </div>
    </div>
  );

  function drawChart(games: GameAudienceEstimate[], svg: SVGSVGElement) {
    const el = svg;
    const width = el.clientWidth || 800;
    const height = 260;
    const margin = { top: 20, right: 30, bottom: 40, left: 60 };
    const w = width - margin.left - margin.right;
    const h = height - margin.top - margin.bottom;

    d3.select(el).selectAll('*').remove();

    const sorted = [...games].sort((a, b) => a.game_date.localeCompare(b.game_date));
    const dates = sorted.map(g => new Date(g.game_date));
    const values = sorted.map(g => g.projected_viewership);

    const x = d3.scaleTime().domain(d3.extent(dates) as [Date, Date]).range([0, w]);
    const y = d3.scaleLinear().domain([0, d3.max(values)! * 1.1]).range([h, 0]);

    const root = d3.select(el)
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Grid lines
    root.append('g')
      .attr('class', 'grid')
      .call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat(() => ''))
      .call(g => {
        g.select('.domain').remove();
        g.selectAll('.tick line').attr('stroke', '#334155').attr('stroke-dasharray', '3,3');
      });

    // Area fill
    const area = d3.area<GameAudienceEstimate>()
      .x(d => x(new Date(d.game_date)))
      .y0(h)
      .y1(d => y(d.projected_viewership))
      .curve(d3.curveCatmullRom);

    root.append('path')
      .datum(sorted)
      .attr('fill', 'rgba(37, 99, 235, 0.15)')
      .attr('d', area);

    // Line
    const line = d3.line<GameAudienceEstimate>()
      .x(d => x(new Date(d.game_date)))
      .y(d => y(d.projected_viewership))
      .curve(d3.curveCatmullRom);

    root.append('path')
      .datum(sorted)
      .attr('fill', 'none')
      .attr('stroke', '#2563EB')
      .attr('stroke-width', 2)
      .attr('d', line);

    // Dots
    root.selectAll('.dot')
      .data(sorted)
      .enter()
      .append('circle')
      .attr('class', 'dot')
      .attr('cx', d => x(new Date(d.game_date)))
      .attr('cy', d => y(d.projected_viewership))
      .attr('r', d => d.is_rivalry ? 6 : 3.5)
      .attr('fill', d => d.is_rivalry ? '#F59E0B' : '#2563EB')
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 1.5)
      .style('cursor', 'pointer')
      .on('click', (_, d) => setSelectedGame(d));

    // Axes
    root.append('g')
      .attr('transform', `translate(0,${h})`)
      .call(d3.axisBottom(x).ticks(6).tickFormat(d => d3.timeFormat('%b %d')(d as Date)))
      .call(g => {
        g.select('.domain').attr('stroke', '#334155');
        g.selectAll('text').attr('fill', '#64748b').attr('font-size', '11');
        g.selectAll('.tick line').attr('stroke', '#334155');
      });

    root.append('g')
      .call(d3.axisLeft(y).ticks(5).tickFormat(d => `${(+d / 1000).toFixed(0)}K`))
      .call(g => {
        g.select('.domain').attr('stroke', '#334155');
        g.selectAll('text').attr('fill', '#64748b').attr('font-size', '11');
        g.selectAll('.tick line').attr('stroke', '#334155');
      });
  }
}

function MiniStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="card">
      <p className="text-xs text-dark-600">{label}</p>
      <p className="text-white font-bold text-xl mt-0.5">{value}</p>
      <p className="text-dark-600 text-xs">{sub}</p>
    </div>
  );
}

function GameList({ title, games, accent, icon }: {
  title: string;
  games: GameAudienceEstimate[];
  accent: string;
  icon: string;
}) {
  return (
    <div className="card">
      <h3 className="section-title mb-3">{icon} {title}</h3>
      <div className="space-y-2">
        {games.map(g => (
          <div key={g.game_id} className="flex items-center justify-between text-sm p-2 bg-dark-700/50 rounded">
            <div>
              <p className="text-white text-xs font-medium">{g.away_team} at {g.home_team}</p>
              <p className="text-dark-600 text-xs">{g.game_date} · {g.timeslot}</p>
            </div>
            <span className={`font-bold ${accent}`}>
              {(g.projected_viewership / 1000).toFixed(0)}K
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-dark-500">
      <span className="animate-spin w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full inline-block" />
      Loading audience analysis...
    </div>
  );
}
