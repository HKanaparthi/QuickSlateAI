import type { NavSection } from '../types';

interface NavbarProps {
  active: NavSection;
  onChange: (section: NavSection) => void;
  hasSchedule: boolean;
}

const NAV_ITEMS: Array<{ id: NavSection; label: string; icon: string; requiresSchedule?: boolean }> = [
  { id: 'schedule', label: 'AI Schedule Generator', icon: '📅' },
  { id: 'conflicts', label: 'Conflict Dashboard', icon: '⚠️', requiresSchedule: true },
  { id: 'travel', label: 'Travel Optimizer', icon: '✈️', requiresSchedule: true },
  { id: 'audience', label: 'Audience Estimator', icon: '📊', requiresSchedule: true },
  { id: 'tournament', label: 'Tournament Bracket', icon: '🏆' },
];

export default function Navbar({ active, onChange, hasSchedule }: NavbarProps) {
  return (
    <aside className="w-64 flex-shrink-0 bg-dark-800 border-r border-dark-700 flex flex-col h-full">
      <div className="p-6 border-b border-dark-700">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-primary-600 rounded-lg flex items-center justify-center text-white font-bold text-lg">
            Q
          </div>
          <div>
            <h1 className="text-white font-bold text-lg leading-none">QuickSlateAI</h1>
            <p className="text-dark-500 text-xs mt-0.5">Sports Scheduling Platform</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {NAV_ITEMS.map((item) => {
          const disabled = item.requiresSchedule && !hasSchedule;
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => !disabled && onChange(item.id)}
              disabled={disabled}
              title={disabled ? 'Generate a schedule first' : undefined}
              className={[
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
                isActive
                  ? 'bg-primary-600 text-white shadow-sm'
                  : disabled
                  ? 'text-dark-600 cursor-not-allowed opacity-50'
                  : 'text-dark-500 hover:text-white hover:bg-dark-700',
              ].join(' ')}
            >
              <span className="text-base">{item.icon}</span>
              <span className="text-left leading-tight">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="p-4 border-t border-dark-700">
        <div className="text-dark-600 text-xs space-y-1">
          <p className="font-medium text-dark-500">Harsha Kanaparthi</p>
          <div className="flex gap-3">
            <a
              href="https://github.com/HKanaparthi"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-primary-500 transition-colors"
            >
              GitHub
            </a>
            <a
              href="https://linkedin.com/in/harsha2003"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-primary-500 transition-colors"
            >
              LinkedIn
            </a>
          </div>
        </div>
      </div>
    </aside>
  );
}
