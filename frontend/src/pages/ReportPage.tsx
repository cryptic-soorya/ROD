import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import * as api from '../lib/api';
import type { Report } from '../lib/types';
import ConfidenceGauge from '../components/ConfidenceGauge';
import './pages.css';

const RECOMMENDATION_SECTIONS: { key: keyof Report['recommendations']; label: string }[] = [
  { key: 'immediate', label: 'Immediate actions' },
  { key: 'customer_recovery', label: 'Customer recovery' },
  { key: 'process_improvement', label: 'Process improvement' },
];

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<'json' | 'pdf' | null>(null);

  useEffect(() => {
    if (!id) return;
    api
      .getReport(Number(id))
      .then(setReport)
      .catch(() => setError('This investigation has no report yet — it may still be in progress.'));
  }, [id]);

  async function handleExport(format: 'json' | 'pdf') {
    if (!id) return;
    setExporting(format);
    try {
      await api.exportReport(Number(id), format);
    } finally {
      setExporting(null);
    }
  }

  if (error) return <div className="banner-error">{error}</div>;
  if (!report) return <p style={{ color: 'var(--color-text-muted)' }}>Loading report…</p>;

  return (
    <div>
      <div className="page-header">
        <div>
          <span className="badge">{report.anomaly_category?.replace(/_/g, ' ')}</span>
          <p style={{ marginTop: 8 }}>Investigation #{report.investigation_id} · {report.total_iterations} iterations</p>
        </div>
      </div>

      <div className="report-top">
        <div className="card card-padded report-headline">
          <div className="section-title">Root cause</div>
          <div className="report-root-cause">{report.root_cause}</div>
          {report.estimated_impact && (
            <div className="report-impact">
              Estimated impact: <strong>{report.estimated_impact}</strong>
            </div>
          )}
          <div className="report-actions">
            <button className="btn btn-secondary" disabled={!!exporting} onClick={() => handleExport('pdf')}>
              {exporting === 'pdf' ? 'Preparing PDF…' : 'Download PDF'}
            </button>
            <button className="btn btn-secondary" disabled={!!exporting} onClick={() => handleExport('json')}>
              {exporting === 'json' ? 'Preparing JSON…' : 'Download JSON'}
            </button>
          </div>
        </div>

        <div className="card card-padded" style={{ display: 'flex', justifyContent: 'center' }}>
          <ConfidenceGauge value={report.confidence_score} />
        </div>
      </div>

      <div className="section-title">Evidence trail</div>
      <div className="card evidence-list">
        {report.evidence.map((step) => (
          <div className="timeline-item" key={step.step} style={{ padding: '16px 20px' }}>
            <div className="timeline-step">{step.step}</div>
            <div className="timeline-body">
              <span className="timeline-tool">{step.tool}</span>
              <div style={{ marginTop: 6, fontSize: 13, color: 'var(--color-text-muted)' }}>{step.finding}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="section-title">Recommendations</div>
      <div className="card card-padded recommend-grid">
        {RECOMMENDATION_SECTIONS.map(({ key, label }) => (
          <div className="recommend-col" key={key}>
            <h4>{label}</h4>
            <ul>
              {(report.recommendations?.[key] ?? []).map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}