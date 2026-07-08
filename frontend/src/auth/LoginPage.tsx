import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { ApiError } from '../lib/api';
import './login.css';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      navigate('/investigations', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Incorrect username or password.');
      } else {
        setError('Could not reach ROD. Is the API running?');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">
          <svg viewBox="0 0 64 64" className="login-mark" aria-hidden="true">
            <circle cx="32" cy="32" r="30" fill="var(--color-primary-dark)" />
            <circle cx="32" cy="32" r="22" fill="none" stroke="var(--color-primary)" strokeWidth="3" />
            <circle cx="32" cy="32" r="14" fill="none" stroke="var(--color-primary-light)" strokeWidth="3" />
            <circle cx="32" cy="32" r="5" fill="#C17A3F" />
          </svg>
          <div>
            <h1 className="login-title">ROD</h1>
            <p className="login-subtitle">Retail Operations Detective</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          {error && <p className="login-error">{error}</p>}

          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="login-hint">
          <span>Demo accounts</span>
          <code>admin / admin123</code>
          <code>category_manager / manager123</code>
          <code>store_manager / store123</code>
        </div>
      </div>
    </div>
  );
}
