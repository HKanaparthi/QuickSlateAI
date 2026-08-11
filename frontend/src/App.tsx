import { useState } from 'react';
import type { Schedule, ValidationResult, ScheduleSummary, NavSection } from './types';
import Navbar from './components/Navbar';
import ConstraintPanel from './components/ConstraintPanel';
import ScheduleGrid from './components/ScheduleGrid';
import ConflictDashboard from './components/ConflictDashboard';
import TravelMap from './components/TravelMap';
import AudienceEstimator from './components/AudienceEstimator';
import TournamentBracket from './components/TournamentBracket';
import { generateSchedule } from './utils/api';

interface AppState {
  schedule: Schedule;
  validation: ValidationResult;
  summary: ScheduleSummary;
}

export default function App() {
  const [activeSection, setActiveSection] = useState<NavSection>('schedule');
  const [appState, setAppState] = useState<AppState | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = async (params: Parameters<typeof generateSchedule>[0]) => {
    setIsGenerating(true);
    setError('');
    try {
      const result = await generateSchedule(params);
      setAppState({
        schedule: result.schedule,
        validation: result.validation,
        summary: result.summary,
      });
      setActiveSection('schedule');
    } catch (e: any) {
      setError(
        e?.response?.data?.detail ||
        'Failed to generate schedule. Make sure the backend is running on port 8000.'
      );
    } finally {
      setIsGenerating(false);
    }
  };

  const handleScheduleUpdate = (updatedSchedule: Schedule, newValidation: ValidationResult) => {
    if (!appState) return;
    setAppState(prev => prev ? { ...prev, schedule: updatedSchedule, validation: newValidation } : null);
  };

  const renderContent = () => {
    if (activeSection === 'tournament') {
      return (
        <div>
          <PageHeader
            title="Tournament Bracket Generator"
            subtitle="Automated brackets with field rotation fairness"
          />
          <TournamentBracket />
        </div>
      );
    }

    if (activeSection === 'schedule' && !appState) {
      if (isGenerating) {
        return (
          <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6">
            <div className="w-14 h-14 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
            <div className="text-center">
              <p className="text-white text-lg font-semibold">Optimizing schedule...</p>
              <p className="text-dark-500 text-sm mt-1">OR-Tools CP-SAT solver running — up to 30 seconds</p>
            </div>
          </div>
        );
      }
      return (
        <div>
          <PageHeader
            title="AI Schedule Generator"
            subtitle="Constraint-optimized season schedules with natural language AI explanations"
          />
          {error && (
            <div className="mb-4 p-4 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
              {error}
            </div>
          )}
          <ConstraintPanel onGenerate={handleGenerate} isLoading={isGenerating} />
        </div>
      );
    }

    if (!appState) return null;

    switch (activeSection) {
      case 'schedule':
        return (
          <div>
            <div className="flex items-center justify-between mb-5">
              <PageHeader
                title="Generated Schedule"
                subtitle={`${appState.schedule.league_id} · ${appState.schedule.total_games} games · Solver: ${appState.schedule.solver_status}`}
                inline
              />

              <button
                onClick={() => setAppState(null)}
                className="btn-secondary text-sm"
              >
                ← New Schedule
              </button>
            </div>
            {error && (
              <div className="mb-4 p-4 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
                {error}
              </div>
            )}
            <ScheduleGrid
              schedule={appState.schedule}
              validation={appState.validation}
              summary={appState.summary}
            />
          </div>
        );

      case 'conflicts':
        return (
          <div>
            <PageHeader
              title="Conflict Dashboard"
              subtitle="Real-time constraint validation with drag-and-drop rescheduling"
            />
            <ConflictDashboard
              schedule={appState.schedule}
              validation={appState.validation}
              onScheduleUpdate={handleScheduleUpdate}
            />
          </div>
        );

      case 'travel':
        return (
          <div>
            <PageHeader
              title="Travel Optimizer"
              subtitle="Team travel analysis with interactive route maps and fairness scoring"
            />
            <TravelMap scheduleId={appState.schedule.id} />
          </div>
        );

      case 'audience':
        return (
          <div>
            <PageHeader
              title="Audience Estimator"
              subtitle="Projected viewership based on timeslot, rivalry status, and market factors"
            />
            <AudienceEstimator scheduleId={appState.schedule.id} />
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="flex h-screen bg-dark-900 text-white overflow-hidden">
      <Navbar
        active={activeSection}
        onChange={setActiveSection}
        hasSchedule={!!appState}
      />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto p-6">
          {renderContent()}
        </div>
      </main>
    </div>
  );
}

function PageHeader({
  title,
  subtitle,
  inline,
}: {
  title: string;
  subtitle: string;
  inline?: boolean;
}) {
  return (
    <div className={inline ? '' : 'mb-6'}>
      <h2 className="text-2xl font-bold text-white">{title}</h2>
      <p className="text-dark-500 text-sm mt-1">{subtitle}</p>
    </div>
  );
}
