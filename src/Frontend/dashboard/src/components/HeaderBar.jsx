import { useState, useRef, useCallback, useEffect } from 'react';

const MenuIcon = () => (
  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <line x1="3" y1="5" x2="17" y2="5" />
    <line x1="3" y1="10" x2="17" y2="10" />
    <line x1="3" y1="15" x2="17" y2="15" />
  </svg>
);

const HomeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
    <polyline points="9 22 9 12 15 12 15 22" />
  </svg>
);

const SettingsIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
  </svg>
);

const BellIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 01-3.46 0" />
  </svg>
);

const HelpIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

const ExportIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

const SearchIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const GridIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
  </svg>
);

const LuasIcon = () => (
  <svg height="16" viewBox="0 0 582.12 151.38" fill="currentColor" style={{ width: 'auto' }}>
    <g transform="translate(-323.46905,-99.43165)">
      <path d="M436.32,240.42c-0.01-5.97-2.98-8.1-9.19-8.1h-62.67c-13.15-0.04-20.51-6.07-20.54-20.82V109.55c-0.01-8.41-4.36-10.13-10.24-10.12c-5.86,0.02-10.22,1.73-10.22,10.12V211.5c0,32.13,18.79,37.16,40.69,37.1h63C433.34,248.6,436.33,246.46,436.32,240.42"/>
      <path d="M564.91,126.19c-5.74,0.01-9.92,1.63-9.92,10.12v91.47c-6.35,3.44-18.86,6.67-32.63,6.69c-57.36,0.06-67.19-41.76-67.71-98.16c-0.08-7.96-3.46-10.12-9.96-10.12c-5.65,0-9.95,1.52-9.93,10.12c0.11,76.34,23.53,114.83,87.59,114.49c22.42-0.12,41.81-7.59,46.16-9.76c4.52-2.26,6.31-5.21,6.3-12.15v-92.6C574.83,127.96,570.85,126.18,564.91,126.19"/>
      <path d="M622,199.99v-54.73c5.85-2.14,15.83-4.55,26.97-4.55c43.86,0,66.88,24.99,76.05,59.28H622z M648.97,124.37c-11.83-0.05-27.41,2.19-40.18,7.42c-3.81,1.62-6.66,3.18-6.65,10.72l-0.02,96.04c0,8.35,4.03,10.12,9.96,10.12c5.74,0,9.92-1.63,9.93-10.12v-22.26h106.27c1,7.19,1.51,14.65,1.58,22.25c0.07,7.95,3.46,10.11,9.96,10.11c5.64,0.01,9.94-1.53,9.93-10.11C749.63,157.8,702.99,124.6,648.97,124.37"/>
      <path d="M899.53,148.54c-1.79,4.29-3.92,4.94-6.91,4.94c-2.12,0-5.44-1.54-8.41-2.76c-10.98-4.51-27.18-9.95-47.73-9.95c-34.18,0-46.41,7.03-46.41,16.45c0,8.6,7.28,11.43,12.94,12.51c10.21,1.96,23.4,4.2,37.54,6.53c15.41,2.54,21.96,3.6,26.39,4.51c17.35,3.55,38.75,10.05,38.64,32.41c-0.13,27.69-28.74,37.72-69.11,37.63c-33.92-0.07-55.3-10.33-63.61-15.33c-4.38-2.65-5.99-5.75-4.52-10.92c0.9-3.19,3.16-6.05,6.79-6.05c2.83,0,5.28,1.46,8.2,2.99c13.82,7.24,29.36,12.89,53.13,12.89c33.68,0,47.79-6.57,47.79-19.33c0-7.35-6.61-13.19-17.51-15.46c-7.17-1.48-15.74-2.85-27.8-4.88c-15.06-2.53-24.27-4.01-31.71-5.23c-14.34-2.35-38.62-7.44-38.66-30.28c-0.04-28.71,35.84-34.88,67.89-34.86c22.57,0.02,43.9,5.31,58.18,12.23C900.26,139.27,902.03,142.55,899.53,148.54"/>
    </g>
  </svg>
);

const DublinBusIcon = () => (
  <svg height="16" viewBox="8 78 180 38" fill="currentColor" style={{ width: 'auto' }}>
    <path d="M88.604 112.007h-3.671l.61-2.446c-1.704 1.658-2.928 2.717-4.849 2.717-1.402 0-2.709-.629-3.181-2.053-.5-1.424.148-3.471.559-5.123 0 0 1.483-6.046 1.709-6.955.244-.975 1.635-1.852 2.437-2.034.733-.167 1.945-.165 1.945-.165l-2.275 9.122c-.188.76-.481 2.047-.382 2.742.102 1.023.561 1.717 1.52 1.717 2.388 0 3.104-2.875 3.623-4.956 0 0 1.182-4.87 1.569-6.401.325-1.27 1.786-1.857 2.5-2.055.549-.151 1.889-.169 1.889-.169l-4.003 16.059z"/>
    <path d="M125.629 98.346c.234-.938 1.055-1.822 2.373-2.108 1.021-.221 1.975-.165 1.975-.165l-.6 2.396c1.484-1.545 3.096-2.729 4.795-2.729 3.477 0 3.693 2.661 2.701 6.652l-2.43 9.739h-3.809l2.064-8.275c.771-3.093 1.006-5.355-.916-5.355-2.387 0-3.355 3.892-3.879 5.986L126 112.132h-3.807l3.436-13.786z"/>
    <path d="M169.617 112.007h-3.67l.609-2.446c-1.701 1.658-2.926 2.717-4.846 2.717-1.404 0-2.709-.629-3.184-2.053-.5-1.424.148-3.471.561-5.123 0 0 1.48-6.046 1.709-6.955.242-.975 1.633-1.852 2.436-2.034.734-.167 1.945-.165 1.945-.165l-2.273 9.122c-.191.76-.484 2.047-.383 2.742.102 1.023.559 1.717 1.52 1.717 2.387 0 3.104-2.875 3.623-4.956 0 0 1.182-4.87 1.57-6.401.322-1.27 1.783-1.857 2.5-2.055.547-.151 1.887-.169 1.887-.169l-4.004 16.059z"/>
    <path d="M151.207 92.435c.213-.855.932-1.081 1.76-1.081 1.803 0 2.529 1.176 1.932 3.571-.324 1.297-.975 2.592-2.035 3.457-1.168.964-2.172.832-3.346.832 0 0 1.523-6.108 1.689-6.779zm-9.019 19.572h6.352c3.232 0 7.146-1.92 8.285-6.479 1.02-4.096-1.637-5.222-3.619-5.453l.074-.298c2.445-.397 5.082-2.193 5.859-5.319.969-3.888-2.176-5.399-4.25-5.724-2.656-.413-6.775.167-7.855 3.891-.307 1.057-4.846 19.382-4.846 19.382zm6.849-10.871c2.988-.267 4.34.99 3.432 4.624-.682 2.74-2.797 4.327-4.299 4.327h-1.363l2.23-8.951z"/>
    <path d="M117.967 87.244s-1.139-.053-2.086.125c-.699.13-2.355 1.366-2.711 2.793 0 0-4.395 18.048-4.752 19.474-.355 1.428.77 2.367 1.402 2.498.857.179 1.916.125 1.916.125l.023-.34 6.208-24.675z"/>
    <path d="M97.475 104.3c.535-2.148 1.787-6.478 4.299-6.478s1.477 4.261.949 6.374c-1.053 4.229-2.502 6.134-4.271 6.134-2.54 0-1.494-3.95-.977-6.03zm-4.912 4.328c-.785 3.15 2.897 3.671 5.558 3.671 1.912 0 4.062-.466 5.715-2.204 1.646-1.704 2.689-4.295 3.232-6.479 1.004-4.021.125-8.008-3.602-8.008-1.598 0-3.338 1.021-4.494 2.692l2.764-11.096s-1.268.163-1.939.38c-.82.265-2.277.827-2.682 2.333-.404 1.506-4.166 17.165-4.552 18.711z"/>
    <path d="M118.549 98.394c.332-1.331 1.816-2.21 2.471-2.331.883-.167 1.947-.115 1.947-.115l-4.006 16.06h-3.807l3.395-13.614zm4.949-10.363c.934 0 1.504.938 1.225 2.058-.279 1.119-1.316 2.057-2.25 2.057s-1.453-.963-1.18-2.057c.273-1.093 1.273-2.058 2.205-2.058z"/>
    <path d="M67.307 91.981c.35-1.406 2.273-1.322 2.273-1.322 3.243 0 4.559 2.64 3.036 8.753-1.898 7.607-4.87 9.851-8.043 9.851l-1.562-.054c0 .001 4.031-16.17 4.296-17.228zm-4.363-.009c-.525 1.99-4.972 19.874-4.972 19.874h6.833c5.004 0 10.298-3.373 12.518-12.503 1.376-5.658-.193-10.276-4.802-11.598 0 0-7.885-2.167-9.577 4.227z"/>
    <path d="M177.141 110.589c.967-.09 2.143-.995 2.496-2.16 1.209-3.974-6.016-1.541-4.934-7.331.635-3.396 3.236-5.446 5.744-5.598 1.375-.084 3.234.666 3.713 1.334.443.62-.801 1.65-1.762 2.514-.057.052.111-1.98-2.326-2.132-.961-.062-2.215.696-2.396 2.055-.471 3.538 6.43 1.086 5.033 7.391-.688 3.101-3.023 5.611-6.33 5.666-1.365.023-4.02-1.221-4.02-1.221s.82-2.426 1.096-3.183c.578-1.583.481 2.959 3.686 2.665z"/>
    <path d="M32.325 97.479h-2.349s-2.277 9.495-2.851 11.438c-.576 1.942-2.228 2.051-2.858 2.051H12.075c-4.334 0-4.517-5.073-1.658-8.202 1.606-1.76 6.777-7.984 7.74-8.955.965-.972 2.283-1.187 2.283-1.187h5.359l-1.104 4.424h-3.643s-1.083 0-1.669.539c-.585.539-6.372 7.444-6.372 7.444s-.349 1.405.284 1.405h10.023l4.277-17.157-1.991-3.239 1.398-5.61h3.431l-.672 2.698h3.521l.673-2.698h3.699l-.673 2.698h3.521l.674-2.698h3.431l-1.399 5.61-3.605 3.239-4.365 17.157h10.109c.634 0 .983-1.405.983-1.405s-2.341-6.905-2.658-7.444c-.319-.539-1.403-.539-1.403-.539l-3.625.012 1.086-4.436h5.359s1.211.215 1.69 1.187c.48.971 2.546 7.195 3.275 8.955 1.296 3.129-1.413 8.202-5.747 8.202H32.115c-.631 0-2.321-.107-1.836-2.051.509-2.046 2.852-11.438 2.852-11.438h-.806zm2.055-4.864s.798-2.481.969-3.885c.169-1.403-.845-2.05-.845-2.05h-.447s-1.335.647-1.865 2.05c-.531 1.404-.969 3.885-.969 3.885h3.157z" fill="#e2982f"/>
  </svg>
);

const HOVER_OPEN_MS = 250;
const LEAVE_CLOSE_MS = 550;
const SEARCH_OPEN_MS = 250;
const SEARCH_CLOSE_MS = 1100;

export default function HeaderBar({ theme, onToggleTheme, filter, onFilterChange }) {
  const [expanded, setExpanded] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [searchError, setSearchError] = useState('');

  const hoverTimer = useRef(null);
  const leaveTimer = useRef(null);
  const searchHoverTimer = useRef(null);
  const searchLeaveTimer = useRef(null);
  const searchInputRef = useRef(null);

  const isDark = theme === 'dark';

  useEffect(() => {
    return () => {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
      if (leaveTimer.current) clearTimeout(leaveTimer.current);
      if (searchHoverTimer.current) clearTimeout(searchHoverTimer.current);
      if (searchLeaveTimer.current) clearTimeout(searchLeaveTimer.current);
    };
  }, []);

  const handleMenuEnter = useCallback(() => {
    if (leaveTimer.current) { clearTimeout(leaveTimer.current); leaveTimer.current = null; }
    setExpanded(true);
    if (!hoverTimer.current) {
      hoverTimer.current = setTimeout(() => {
        setDropdownOpen(true);
        hoverTimer.current = null;
      }, HOVER_OPEN_MS);
    }
  }, []);

  const handleMenuLeave = useCallback(() => {
    if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    leaveTimer.current = setTimeout(() => {
      setExpanded(false);
      setDropdownOpen(false);
      leaveTimer.current = null;
    }, LEAVE_CLOSE_MS);
  }, []);

  const handleHeaderClick = useCallback(() => {
    if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    setExpanded(true);
    setDropdownOpen((prev) => !prev);
  }, []);

  const handleHome = useCallback(() => {
    onFilterChange('all');
  }, [onFilterChange]);

  const handleSearchEnter = useCallback(() => {
    if (searchLeaveTimer.current) { clearTimeout(searchLeaveTimer.current); searchLeaveTimer.current = null; }
    if (!searchHoverTimer.current) {
      searchHoverTimer.current = setTimeout(() => {
        setSearchExpanded(true);
        searchHoverTimer.current = null;
      }, SEARCH_OPEN_MS);
    }
  }, []);

  const handleSearchLeave = useCallback(() => {
    if (searchHoverTimer.current) { clearTimeout(searchHoverTimer.current); searchHoverTimer.current = null; }
    const isFocused = searchInputRef.current && document.activeElement === searchInputRef.current;
    if (searchValue.trim() || isFocused) return;
    searchLeaveTimer.current = setTimeout(() => {
      setSearchExpanded(false);
      searchLeaveTimer.current = null;
    }, SEARCH_CLOSE_MS);
  }, [searchValue]);

  const handleSearchSubmit = useCallback(() => {
    const trimmed = searchValue.trim();
    if (!trimmed) {
      setSearchError('Please enter a search term');
      setTimeout(() => setSearchError(''), 2000);
      return;
    }
    setSearchError('Search not yet implemented');
    setTimeout(() => setSearchError(''), 2000);
    if (searchInputRef.current) searchInputRef.current.blur();
  }, [searchValue]);

  const handleSearchClick = useCallback(() => {
    if (searchHoverTimer.current) { clearTimeout(searchHoverTimer.current); searchHoverTimer.current = null; }
    if (searchExpanded) {
      handleSearchSubmit();
    } else {
      setSearchExpanded(true);
    }
  }, [searchExpanded, handleSearchSubmit]);

  const handleSearchKeyDown = useCallback((e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSearchSubmit();
    }
    if (e.key === 'Escape') {
      setSearchError('');
      if (searchInputRef.current) searchInputRef.current.blur();
    }
  }, [handleSearchSubmit]);

  const handleSearchBlur = useCallback(() => {
    if (!searchValue.trim()) {
      searchLeaveTimer.current = setTimeout(() => {
        setSearchExpanded(false);
        searchLeaveTimer.current = null;
      }, SEARCH_CLOSE_MS);
    }
  }, [searchValue]);

  return (
    <header className="header-bar">
      <div className="header-left">
        <div
          className="menu-area"
          onMouseEnter={handleMenuEnter}
          onMouseLeave={handleMenuLeave}
        >
          <button
            className={`menu-header ${expanded ? 'menu-header-expanded' : ''} ${dropdownOpen ? 'menu-header-open' : ''}`}
            onClick={handleHeaderClick}
            aria-label="Menu"
          >
            <MenuIcon />
            <span className="menu-header-label">Menu</span>
          </button>

          <div className={`menu-dropdown ${dropdownOpen ? 'menu-dropdown-open' : ''}`}>
            <button className="menu-item" onClick={onToggleTheme}>
              <span className="menu-item-label">Dark Mode</span>
              <span className={`toggle-track ${isDark ? 'toggle-on' : ''}`}>
                <span className="toggle-knob" />
              </span>
            </button>

            <div className="menu-divider" />

            <button className="menu-item" onClick={() => {}}>
              <BellIcon />
              <span className="menu-item-label">Notifications</span>
            </button>

            <button className="menu-item" onClick={() => {}}>
              <ExportIcon />
              <span className="menu-item-label">Export Data</span>
            </button>

            <button className="menu-item" onClick={() => {}}>
              <SettingsIcon />
              <span className="menu-item-label">Settings</span>
            </button>

            <div className="menu-divider" />

            <button className="menu-item" onClick={() => {}}>
              <HelpIcon />
              <span className="menu-item-label">Help & Support</span>
            </button>
          </div>
        </div>

        <button className="icon-btn" onClick={handleHome} aria-label="Home">
          <HomeIcon />
        </button>

        <h1 className="header-title">Transit Dashboard</h1>
      </div>

      <div className="header-right">
        <div className="filter-pill">
          <button
            className={`filter-seg filter-seg-all ${filter === 'all' ? 'filter-seg-active' : ''}`}
            onClick={() => onFilterChange('all')}
          >
            <GridIcon />
            <span className="filter-seg-label">All</span>
          </button>
          <button
            className={`filter-seg filter-seg-luas ${filter === 'luas' ? 'filter-seg-active' : ''}`}
            onClick={() => onFilterChange('luas')}
          >
            <LuasIcon />
          </button>
          <button
            className={`filter-seg filter-seg-bus ${filter === 'bus' ? 'filter-seg-active' : ''}`}
            onClick={() => onFilterChange('bus')}
          >
            <DublinBusIcon />
          </button>
        </div>
        <div
          className="search-area"
          onMouseEnter={handleSearchEnter}
          onMouseLeave={handleSearchLeave}
        >
          <div className={`search-bar ${searchExpanded ? 'search-bar-expanded' : ''}`}>
            <input
              ref={searchInputRef}
              className={`search-input ${searchError ? 'search-input-error' : ''}`}
              type="text"
              placeholder={searchError || 'Search...'}
              value={searchValue}
              onChange={(e) => { setSearchValue(e.target.value); setSearchError(''); }}
              onKeyDown={handleSearchKeyDown}
              onBlur={handleSearchBlur}
              tabIndex={searchExpanded ? 0 : -1}
            />
            <button
              className="search-btn"
              onClick={handleSearchClick}
              aria-label="Search"
            >
              <SearchIcon />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
