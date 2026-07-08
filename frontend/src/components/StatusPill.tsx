import type { InvestigationStatus } from '../lib/types';
import './ui.css';

const LABELS: Record<InvestigationStatus, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  completed: 'Completed',
  escalated: 'Escalated',
};

export default function StatusPill({ status }: { status: InvestigationStatus }) {
  return (
    <span className={`pill pill-${status}`}>
      <span className={`pill-dot ${status === 'in_progress' ? 'pulse' : ''}`} />
      {LABELS[status]}
    </span>
  );
}
