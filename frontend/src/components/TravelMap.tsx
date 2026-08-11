import { useEffect, useState, useRef } from 'react';
import type { TravelAnalysis } from '../types';
import { getTravelAnalysis } from '../utils/api';
import { TEAMS_BY_ID } from '../data/teams';

interface TravelMapProps {
  scheduleId: string;
}

export default function TravelMap({ scheduleId }: TravelMapProps) {
  const [analysis, setAnalysis] = useState<TravelAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTeam, setSelectedTeam] = useState<string>('');
  const [error, setError] = useState('');
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMap = useRef<any>(null);
  const polylines = useRef<any[]>([]);
  const markers = useRef<any[]>([]);

  useEffect(() => {
    getTravelAnalysis(scheduleId)
      .then(data => {
        setAnalysis(data);
        if (Object.keys(data.team_stats).length > 0) {
          setSelectedTeam(Object.keys(data.team_stats)[0]);
        }
      })
      .catch(() => setError('Failed to load travel analysis'))
      .finally(() => setLoading(false));
  }, [scheduleId]);

  useEffect(() => {
    if (!mapRef.current || !analysis) return;
    if (typeof window === 'undefined') return;

    import('leaflet').then(L => {
      if (!leafletMap.current) {
        leafletMap.current = L.map(mapRef.current!, {
          center: [35.5, -79.0],
          zoom: 7,
        });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '© OpenStreetMap contributors',
        }).addTo(leafletMap.current);
      }

      // Clear existing
      polylines.current.forEach(p => p.remove());
      markers.current.forEach(m => m.remove());
      polylines.current = [];
      markers.current = [];

      // Add venue markers
      analysis.venues.forEach(v => {
        const marker = L.circleMarker([v.lat, v.lng], {
          radius: 8,
          fillColor: '#2563EB',
          color: '#fff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.8,
        })
          .addTo(leafletMap.current)
          .bindPopup(`<b>${v.name}</b><br>${v.city}<br>Capacity: ${v.capacity.toLocaleString()}`);
        markers.current.push(marker);
      });

      // Add routes for selected team
      if (selectedTeam && analysis.team_stats[selectedTeam]) {
        const stats = analysis.team_stats[selectedTeam];
        const team = TEAMS_BY_ID[selectedTeam];
        const color = team?.color || '#10B981';

        stats.travel_legs.forEach(leg => {
          const line = L.polyline(
            [[leg.from_lat, leg.from_lng], [leg.to_lat, leg.to_lng]],
            { color, weight: 2.5, opacity: 0.8, dashArray: '5, 5' }
          )
            .addTo(leafletMap.current)
            .bindPopup(`<b>${leg.from_city} → ${leg.to_city}</b><br>${leg.distance_miles} miles<br>${leg.game_date}`);
          polylines.current.push(line);
        });
      }
    });
  }, [analysis, selectedTeam]);

  if (loading) return <LoadingSpinner label="Loading travel analysis..." />;
  if (error) return <div className="card text-danger p-6">{error}</div>;
  if (!analysis) return null;

  const selectedStats = selectedTeam ? analysis.team_stats[selectedTeam] : null;
  const teamList = Object.values(analysis.team_stats);

  return (
    <div className="space-y-5">
      {/* Stats Row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatMini label="League Avg Miles" value={`${analysis.league_avg_miles.toLocaleString()}`} />
        {selectedStats && (
          <>
            <StatMini label={`${selectedStats.team_name} Total`} value={`${selectedStats.total_miles.toLocaleString()} mi`} />
            <StatMini label="Avg / Week" value={`${selectedStats.avg_miles_per_week.toLocaleString()} mi`} />
            <StatMini label="Longest Trip" value={`${selectedStats.longest_trip_miles.toLocaleString()} mi`} />
          </>
        )}
      </div>

      {/* Team Selector */}
      <div className="card">
        <div className="flex items-center gap-4 mb-3">
          <h3 className="section-title">Interactive Travel Map</h3>
          <select
            value={selectedTeam}
            onChange={e => setSelectedTeam(e.target.value)}
            className="input ml-auto text-sm"
          >
            {teamList.map(t => (
              <option key={t.team_id} value={t.team_id}>{t.team_name}</option>
            ))}
          </select>
        </div>
        <div ref={mapRef} className="w-full rounded-lg overflow-hidden" style={{ height: '400px', background: '#1e293b' }} />
      </div>

      {/* Fairness Analysis */}
      <div className="card">
        <h3 className="section-title mb-4">Travel Fairness Analysis</h3>
        <div className="space-y-2">
          {analysis.fairness_analysis
            .sort((a, b) => b.total_miles - a.total_miles)
            .map(f => {
              const pct = f.pct_vs_avg;
              const barWidth = Math.min(100, (f.total_miles / Math.max(...analysis.fairness_analysis.map(x => x.total_miles))) * 100);
              const team = TEAMS_BY_ID[f.team_id];
              return (
                <div key={f.team_id} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: team?.color }} />
                      <span className="text-white font-medium">{f.team_name}</span>
                      {f.flagged && <span className="text-xs text-danger">⚠ outlier</span>}
                    </div>
                    <div className="text-right">
                      <span className="text-dark-400 mr-3">{f.total_miles.toLocaleString()} mi</span>
                      <span className={pct > 0 ? 'text-danger text-xs' : 'text-success text-xs'}>
                        {pct > 0 ? '+' : ''}{pct}% vs avg
                      </span>
                    </div>
                  </div>
                  <div className="h-2 bg-dark-700 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${barWidth}%`,
                        backgroundColor: f.flagged ? '#EF4444' : team?.color || '#2563EB',
                      }}
                    />
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {/* Hotel Suggestions */}
      {analysis.hotel_suggestions.length > 0 && (
        <div className="card">
          <h3 className="section-title mb-3">Hotel Grouping Suggestions</h3>
          <div className="space-y-2">
            {analysis.hotel_suggestions.map((s, i) => (
              <div key={i} className="p-3 bg-dark-700/50 rounded-lg border border-dark-700">
                <div className="flex items-start gap-2">
                  <span className="text-primary-500">🏨</span>
                  <div>
                    <p className="text-sm text-dark-400">{s.message}</p>
                    <p className="text-xs text-success mt-1">
                      Saves ~{s.savings_miles.toFixed(0)} miles of travel
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <p className="text-xs text-dark-600">{label}</p>
      <p className="text-white font-bold text-base mt-0.5">{value}</p>
    </div>
  );
}

function LoadingSpinner({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-dark-500">
      <span className="animate-spin w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full inline-block" />
      {label}
    </div>
  );
}
