import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import './appshell.css';

const NAV_ITEMS = [
  { to: '/investigations', label: 'Investigations', scope: null },
  { to: '/investigations/new', label: 'New Investigation', scope: null },
  { to: '/capabilities', label: 'Capabilities', scope: null },
  { to: '/knowledge', label: 'Knowledge Base', scope: 'write:knowledge' },
];

const ROLE_LABELS: Record<string, string> = {
  admin: 'Admin',
  category_manager: 'Category Manager',
  store_manager: 'Store Manager',
};

export default function AppShell() {
  const { user, hasScope, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="shell">
      <aside className="shell-sidebar">
        <div className="shell-brand">
          <svg viewBox="0 0 64 64" className="shell-mark" aria-hidden="true">
            <circle cx="32" cy="32" r="30" fill="var(--color-primary-dark)" />
            <circle cx="32" cy="32" r="22" fill="none" stroke="var(--color-primary)" strokeWidth="3" />
            <circle cx="32" cy="32" r="14" fill="none" stroke="var(--color-primary-light)" strokeWidth="3" />
            <circle cx="32" cy="32" r="5" fill="#C17A3F" />
          </svg>
          <span className="shell-wordmark">ROD</span>
        </div>

        <nav className="shell-nav">
          {NAV_ITEMS.filter((item) => !item.scope || hasScope(item.scope)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/investigations'}
              className={({ isActive }) => `shell-nav-item ${isActive ? 'active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="shell-user">
          <div className="shell-user-role">{user ? ROLE_LABELS[user.role] ?? user.role : ''}</div>
          <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
