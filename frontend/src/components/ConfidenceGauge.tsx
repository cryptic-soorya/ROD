const SIZE = 120;
const STROKE = 10;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function ConfidenceGauge({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value));
  const offset = CIRCUMFERENCE * (1 - pct);
  const color = pct >= 0.7 ? 'var(--color-complete)' : 'var(--color-escalated)';

  return (
    <div style={{ position: 'relative', width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={STROKE}
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          style={{ transition: 'stroke-dashoffset 0.4s ease' }}
        />
      </svg>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--color-primary-dark)' }}>
          {Math.round(pct * 100)}%
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-text-faint)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          confidence
        </span>
      </div>
    </div>
  );
}
