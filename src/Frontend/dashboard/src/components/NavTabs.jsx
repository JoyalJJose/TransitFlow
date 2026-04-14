import { NavLink } from 'react-router-dom';

const tabs = [
  { to: '/', label: 'Live' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/scheduling', label: 'Scheduling' },
  { to: '/controls', label: 'Controls' },
];

export default function NavTabs() {
  return (
    <nav className="header-nav">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.to === '/'}
          className={({ isActive }) => `nav-pill${isActive ? ' nav-pill-active' : ''}`}
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
