"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  ClipboardList,
  Gauge,
  LogOut,
  RefreshCw,
  Users,
  DatabaseBackup,
} from "lucide-react";

function localDateTime(date) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 19);
}

function formatDuration(seconds = 0) {
  const value = Number(seconds || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDateTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function defaultFilters() {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 7);
  return { start: localDateTime(start), end: localDateTime(end), agent: "", source: "", direction: "", status: "" };
}

function last24Filters() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  return { start: localDateTime(start), end: localDateTime(end) };
}

function pageSlice(rows, page, perPage) {
  const safePage = Math.max(page, 1);
  const start = (safePage - 1) * perPage;
  return rows.slice(start, start + perPage);
}

export default function Dashboard() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [users, setUsers] = useState([]);
  const [newUser, setNewUser] = useState({ username: "", password: "", full_name: "", role: "user" });
  const [filters, setFilters] = useState(defaultFilters);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [activeView, setActiveView] = useState("overview");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [callPage, setCallPage] = useState({ calls: [], pagination: { page: 1, per_page: 10, total: 0, pages: 0 } });
  const [callsLoading, setCallsLoading] = useState(false);

  async function loadDashboard(activeFilters = filters) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams(activeFilters);
    try {
      const response = await fetch(`/api/dashboard?${params.toString()}`, { cache: "no-store" });
      const result = await response.json();
      if (response.status === 401) {
        setUser(null);
        return;
      }
      if (!response.ok) throw new Error(result.error || `API returned ${response.status}`);
      setData(result);
    } catch (err) {
      setError(err.message || "Could not load dashboard");
    } finally {
      setLoading(false);
    }
  }

  async function loadCalls(page = 1, activeFilters = filters, perPage = rowsPerPage) {
    setCallsLoading(true);
    setError("");
    const params = new URLSearchParams({
      ...activeFilters,
      page: String(page),
      per_page: String(perPage),
    });
    try {
      const response = await fetch(`/api/calls?${params.toString()}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `API returned ${response.status}`);
      setCallPage(result);
    } catch (err) {
      setError(err.message || "Could not load call register");
    } finally {
      setCallsLoading(false);
    }
  }

  useEffect(() => {
    loadSession();
  }, []);

  useEffect(() => {
    if (activeView === "calls") loadCalls(1, filters, rowsPerPage);
  }, [activeView, rowsPerPage]);

  useEffect(() => {
    if (activeView === "admin" && user?.role === "admin") {
      loadUsers();
      return;
    }
    if (activeView !== "calls") {
      loadDashboard(last24Filters());
    }
  }, [activeView]);

  async function loadSession() {
    setAuthLoading(true);
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) {
        setUser(null);
        return;
      }
      setUser(result.user);
      await loadDashboard(last24Filters());
    } finally {
      setAuthLoading(false);
    }
  }

  async function login(event) {
    event.preventDefault();
    setError("");
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(loginForm),
    });
    const result = await response.json();
    if (!response.ok) {
      setError(result.error || "Login failed");
      return;
    }
    setUser(result.user);
    await loadDashboard(last24Filters());
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    setData(null);
    setActiveView("overview");
  }

  async function loadUsers() {
    const response = await fetch("/api/users", { cache: "no-store" });
    const result = await response.json();
    if (response.ok) setUsers(result.users || []);
  }

  async function createPortalUser(event) {
    event.preventDefault();
    setError("");
    const response = await fetch("/api/users", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(newUser),
    });
    const result = await response.json();
    if (!response.ok) {
      setError(result.error || "Could not create user");
      return;
    }
    setNewUser({ username: "", password: "", full_name: "", role: "user" });
    await loadUsers();
  }

  async function updatePortalUser(userId, payload) {
    setError("");
    const response = await fetch(`/api/users/${userId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not update user");
    await loadUsers();
    return result.user;
  }

  async function setPortalUserPassword(userId, password) {
    setError("");
    const response = await fetch(`/api/users/${userId}/password`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not change password");
    return true;
  }

  async function deletePortalUser(userId) {
    setError("");
    const response = await fetch(`/api/users/${userId}`, {
      method: "DELETE",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not delete user");
    await loadUsers();
    return true;
  }

  function updateFilter(event) {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  function submit(event) {
    event.preventDefault();
    if (activeView === "calls") loadCalls(1, filters, rowsPerPage);
  }

  async function syncFromPbx() {
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/sync?days=1", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Sync returned ${response.status}`);
      setMessage(
        `Synced ${result.calls?.stored || 0} calls and ${result.agents?.inserted || 0} new agents. ` +
          `${result.agents?.updated || 0} agents updated. CDR range: ${result.start} to ${result.end}.`
      );
      await loadDashboard(last24Filters());
      if (activeView === "calls") await loadCalls(1, filters, rowsPerPage);
    } catch (err) {
      setError(err.message || "Could not sync from PBX");
    } finally {
      setSyncing(false);
    }
  }

  const totals = data?.totals || {};
  const summary = data?.summary || {};
  const agents = data?.agents || [];
  const agentDirectory = data?.agent_directory || [];
  const hasData = !loading && Number(totals.total_calls || 0) > 0;
  const isAdmin = user?.role === "admin";
  const navItems = [
    { key: "overview", label: "Dashboard", icon: Gauge },
    { key: "calls", label: "Call Register", icon: ClipboardList },
    { key: "agents", label: "Agent Activity", icon: Activity },
    { key: "summary", label: "Call Summary", icon: BarChart3 },
    ...(isAdmin ? [{ key: "admin", label: "Users", icon: Users }] : []),
  ];

  if (authLoading) {
    return <div className="auth-screen"><div className="auth-card"><h1>PBX Performance Portal</h1><p>Loading session</p></div></div>;
  }

  if (!user) {
    return (
      <div className="auth-screen">
        <form className="auth-card" onSubmit={login}>
          <h1>PBX Performance Portal</h1>
          <p>Sign in to view call-center performance.</p>
          {error ? <div className="notice">{error}</div> : null}
          <label>
            Username
            <input value={loginForm.username} onChange={(event) => setLoginForm({ ...loginForm, username: event.target.value })} />
          </label>
          <label>
            Password
            <input type="password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} />
          </label>
          <button type="submit">Sign in</button>
        </form>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>PBX</span>
          <strong>Performance Portal</strong>
        </div>
        <nav>
          {navItems.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={activeView === key ? "nav-active" : ""}
              type="button"
              onClick={() => setActiveView(key)}
            >
              <Icon size={16} className="nav-icon" />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <p className="sidebar-user">{user.full_name || user.username}</p>
          <button type="button" className="nav-logout" onClick={logout}>
            <LogOut size={15} />
            <span>Logout</span>
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">FreePBX reporting store</p>
            <h1>Call center performance</h1>
            <p className="session-line">{user.role}</p>
          </div>
          {activeView === "calls" ? (
            <form className="filters" onSubmit={submit}>
              <div className="filter-grid">
                <label>
                  Start
                  <input type="datetime-local" step="1" name="start" value={filters.start} onChange={updateFilter} />
                </label>
                <label>
                  End
                  <input type="datetime-local" step="1" name="end" value={filters.end} onChange={updateFilter} />
                </label>
                <label>
                  Agent
                  <input type="text" name="agent" placeholder="1001" value={filters.agent} onChange={updateFilter} />
                </label>
                <label>
                  Source
                  <input type="text" name="source" placeholder="Search source" value={filters.source} onChange={updateFilter} />
                </label>
                <label>
                  Direction
                  <select name="direction" value={filters.direction} onChange={updateFilter}>
                    <option value="">All</option>
                    <option value="inbound">Inbound</option>
                    <option value="outbound">Outbound</option>
                  </select>
                </label>
                <label>
                  Status
                  <select name="status" value={filters.status} onChange={updateFilter}>
                    <option value="">All</option>
                    <option value="Answered">Answered</option>
                    <option value="No Answer">No Answer</option>
                    <option value="Busy">Busy</option>
                    <option value="Failed">Failed</option>
                    <option value="Congestion">Congestion</option>
                    <option value="Canceled">Canceled</option>
                  </select>
                </label>
                <label>
                  Rows/page
                  <select value={rowsPerPage} onChange={(event) => setRowsPerPage(Number(event.target.value))}>
                    {[10, 20, 50, 100].map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="filter-actions">
                <button type="submit" className="action-button" disabled={loading}>
                  <RefreshCw size={15} />
                  <span>{loading ? "Loading" : "Refresh"}</span>
                </button>
                {user.role === "admin" ? (
                  <button type="button" className="action-button secondary" disabled={syncing} onClick={syncFromPbx}>
                    <DatabaseBackup size={15} />
                    <span>{syncing ? "Syncing" : "Sync PBX"}</span>
                  </button>
                ) : null}
              </div>
            </form>
          ) : (
            <div className="overview-actions">
              <span className="range-pill">Last 24 hours</span>
              <label className="compact-select">
                Rows/page
                <select value={rowsPerPage} onChange={(event) => setRowsPerPage(Number(event.target.value))}>
                  {[10, 20, 50, 100].map((value) => (
                    <option key={value} value={value}>{value}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="action-button" disabled={loading} onClick={() => loadDashboard(last24Filters())}>
                <RefreshCw size={15} />
                <span>{loading ? "Loading" : "Refresh"}</span>
              </button>
              {user.role === "admin" ? (
                <button type="button" className="action-button secondary" disabled={syncing} onClick={syncFromPbx}>
                  <DatabaseBackup size={15} />
                  <span>{syncing ? "Syncing" : "Sync PBX"}</span>
                </button>
              ) : null}
            </div>
          )}
        </header>

        <main>
          {error ? <div className="notice">{error}</div> : null}
          {message ? <div className="notice success">{message}</div> : null}
          {!hasData ? (
            <section className="empty-state">
              {user.role === "admin" ? (
                <>
                  <h2>No real PBX records in the portal database</h2>
                  <p>Configure the FreePBX database variables, run a sync, and this dashboard will populate from imported CDR rows.</p>
                  <button type="button" onClick={syncFromPbx} disabled={syncing}>{syncing ? "Syncing" : "Sync PBX now"}</button>
                </>
              ) : (
                <>
                  <h2>No call records available</h2>
                  <p>There is no data to display for the selected period.</p>
                </>
              )}
            </section>
          ) : null}

          {activeView === "overview" ? (
            <>
              <section className="status-row">
                <Metric label="Total calls" value={totals.total_calls || 0} />
                <Metric label="Received" value={summary.received_calls || 0} />
                <Metric label="Hung before answer" value={summary.hanged_before_received || 0} tone="warn" />
                <Metric label="Answer rate" value={`${totals.answer_rate || 0}%`} />
                <Metric label="Avg duration" value={formatDuration(summary.avg_duration_seconds)} />
                <Metric label="Avg talk time" value={formatDuration(totals.avg_talk_seconds)} />
              </section>

              <section className="dashboard-grid">
                <Panel title="Call Volume Trend" detail="Last 24 hours">
                  <LineTrendChart trend={data?.trend || []} />
                </Panel>
                <Panel title="Call Outcomes">
                  <OutcomePie summary={summary} totals={totals} />
                </Panel>
              </section>

              <section className="dashboard-grid tight">
                <Panel title="Duration Histogram">
                  <DurationHistogram bands={data?.duration_bands || []} />
                </Panel>
                <Ranking title="Top Call Sources" rows={data?.top_sources || []} />
                <Ranking title="Top Destinations" rows={data?.top_destinations || []} />
              </section>
            </>
          ) : null}

          {activeView === "calls" ? (
            <CallRegister
              calls={callPage.calls}
              pagination={callPage.pagination}
              loading={callsLoading}
              onPage={(page) => loadCalls(page, filters, rowsPerPage)}
            />
          ) : null}
          {activeView === "agents" ? (
            <AgentActivity
              agents={data?.agent_activity || []}
              detail={agents}
              directory={agentDirectory}
              rowsPerPage={rowsPerPage}
            />
          ) : null}
          {activeView === "summary" ? <CallSummary summary={summary} agents={agents} rowsPerPage={rowsPerPage} /> : null}
          {activeView === "admin" && user.role === "admin" ? (
            <UserAdmin
              currentUser={user}
              users={users}
              newUser={newUser}
              setNewUser={setNewUser}
              onCreate={createPortalUser}
              onUpdateUser={updatePortalUser}
              onChangePassword={setPortalUserPassword}
              onDeleteUser={deletePortalUser}
              setError={setError}
              setMessage={setMessage}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Panel({ title, detail, children }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {detail ? <span>{detail}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Ranking({ title, rows }) {
  const max = Math.max(...rows.map((row) => row.calls), 1);
  return (
    <Panel title={title}>
      <div className="ranking-list">
        {rows.map((row) => (
          <div className="ranking-row" key={row.value}>
            <span>{row.value}</span>
            <div><b style={{ width: `${(row.calls / max) * 100}%` }} /></div>
            <strong>{row.calls}</strong>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function LineTrendChart({ trend }) {
  if (!trend.length) return <p className="chart-empty">No trend data in the last 24 hours.</p>;
  const width = 560;
  const height = 220;
  const pad = 28;
  const plotWidth = width - pad * 2;
  const plotHeight = height - pad * 2;
  const maxCalls = Math.max(...trend.map((point) => point.calls), 1);
  const step = trend.length > 1 ? plotWidth / (trend.length - 1) : 0;

  const callsPoints = trend.map((point, index) => {
    const x = pad + index * step;
    const y = pad + (1 - point.calls / maxCalls) * plotHeight;
    return { x, y, calls: point.calls };
  });
  const answeredPoints = trend.map((point, index) => {
    const x = pad + index * step;
    const y = pad + (1 - (point.answered || 0) / maxCalls) * plotHeight;
    return { x, y };
  });
  const callsPath = callsPoints.map((point) => `${point.x},${point.y}`).join(" ");
  const answeredPath = answeredPoints.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <div className="line-chart-wrap">
      <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Call volume trend">
        {[0, 1, 2, 3, 4].map((stepIndex) => {
          const y = pad + (plotHeight / 4) * stepIndex;
          return <line key={stepIndex} x1={pad} y1={y} x2={width - pad} y2={y} className="chart-grid" />;
        })}
        <polyline points={callsPath} className="chart-line calls" />
        <polyline points={answeredPath} className="chart-line answered" />
        {callsPoints.map((point, index) => (
          <circle key={index} cx={point.x} cy={point.y} r="3" className="chart-point calls" />
        ))}
      </svg>
      <div className="chart-legend">
        <span><b className="swatch calls" /> Total calls</span>
        <span><b className="swatch answered" /> Answered</span>
      </div>
    </div>
  );
}

function OutcomePie({ summary, totals }) {
  const slices = [
    { label: "Answered", value: Number(summary.answered_calls || 0), color: "#2f8f84" },
    { label: "Hung before answer", value: Number(summary.hanged_before_received || 0), color: "#d07a2d" },
    { label: "Failed / Busy", value: Number(summary.failed_calls || 0), color: "#b74d4d" },
  ];
  const sum = slices.reduce((acc, item) => acc + item.value, 0);
  const other = Math.max(Number(totals.total_calls || 0) - sum, 0);
  if (other > 0) slices.push({ label: "Other", value: other, color: "#6f7d87" });
  const total = slices.reduce((acc, item) => acc + item.value, 0);

  if (!total) return <p className="chart-empty">No outcome data available.</p>;

  let cursor = 0;
  const segments = slices
    .filter((item) => item.value > 0)
    .map((item) => {
      const start = (cursor / total) * 100;
      cursor += item.value;
      const end = (cursor / total) * 100;
      return `${item.color} ${start}% ${end}%`;
    });

  return (
    <div className="pie-layout">
      <div className="donut" style={{ background: `conic-gradient(${segments.join(", ")})` }}>
        <div className="donut-hole">
          <strong>{total}</strong>
          <span>calls</span>
        </div>
      </div>
      <div className="pie-legend">
        {slices.filter((item) => item.value > 0).map((item) => (
          <div key={item.label}>
            <span><b style={{ background: item.color }} /> {item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function DurationHistogram({ bands }) {
  if (!bands.length) return <p className="chart-empty">No duration distribution data.</p>;
  const max = Math.max(...bands.map((band) => band.calls), 1);
  return (
    <div className="histogram">
      {bands.map((band) => (
        <div key={band.label} className="hist-col">
          <span className="hist-count">{band.calls}</span>
          <div className="hist-track">
            <b className="hist-bar" style={{ height: `${Math.max((band.calls / max) * 100, band.calls ? 6 : 0)}%` }} />
          </div>
          <small>{band.label}</small>
        </div>
      ))}
    </div>
  );
}

function CallRegister({ calls, pagination, loading, onPage }) {
  return (
    <section className="table-section">
      <div className="panel-head">
        <h2>Call Register</h2>
        <span>
          {loading ? "Loading" : `${pagination.total} records, page ${pagination.page} of ${pagination.pages || 1}`}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Status</th>
              <th>Source</th>
              <th>Presented CLI</th>
              <th>Destination</th>
              <th>Agent</th>
              <th>Direction</th>
              <th>Duration</th>
              <th>Talk</th>
              <th>Ring</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call, index) => (
              <tr key={`${call.time}-${index}`}>
                <td>{formatDateTime(call.time)}</td>
                <td><span className={`status ${call.status === "Answered" ? "ok" : "bad"}`}>{call.status}</span></td>
                <td>{call.source}</td>
                <td>{call.raw_source && call.raw_source !== call.source ? call.raw_source : "-"}</td>
                <td>{call.destination}</td>
                <td>{call.agent}</td>
                <td>{call.direction}</td>
                <td>{formatDuration(call.duration_seconds)}</td>
                <td>{formatDuration(call.talk_seconds)}</td>
                <td>{formatDuration(call.ring_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <button type="button" disabled={loading || pagination.page <= 1} onClick={() => onPage(pagination.page - 1)}>
          Previous
        </button>
        <span>{pagination.page} / {pagination.pages || 1}</span>
        <button
          type="button"
          disabled={loading || pagination.page >= pagination.pages}
          onClick={() => onPage(pagination.page + 1)}
        >
          Next
        </button>
      </div>
    </section>
  );
}

function AgentActivity({ agents, detail, directory, rowsPerPage }) {
  const activityPerPage = rowsPerPage;
  const efficiencyPerPage = rowsPerPage;
  const directoryPerPage = rowsPerPage;
  const [activityPage, setActivityPage] = useState(1);
  const [efficiencyPage, setEfficiencyPage] = useState(1);
  const [directoryPage, setDirectoryPage] = useState(1);

  const activityPages = Math.max(Math.ceil(agents.length / activityPerPage), 1);
  const efficiencyPages = Math.max(Math.ceil(detail.length / efficiencyPerPage), 1);
  const directoryPages = Math.max(Math.ceil(directory.length / directoryPerPage), 1);

  useEffect(() => {
    setActivityPage((current) => Math.min(current, activityPages));
  }, [activityPages]);
  useEffect(() => {
    setEfficiencyPage((current) => Math.min(current, efficiencyPages));
  }, [efficiencyPages]);
  useEffect(() => {
    setDirectoryPage((current) => Math.min(current, directoryPages));
  }, [directoryPages]);

  const visibleActivity = pageSlice(agents, activityPage, activityPerPage);
  const visibleEfficiency = pageSlice(detail, efficiencyPage, efficiencyPerPage);
  const visibleDirectory = pageSlice(directory, directoryPage, directoryPerPage);

  return (
    <>
      <section className="dashboard-grid">
        <Panel title="Agent Active Times">
          <div className="agent-list">
            {visibleActivity.map((agent) => (
              <div className="agent-card" key={agent.agent}>
                <div>
                  <strong>{agent.agent_label || agent.agent}</strong>
                  <span>{agent.calls} calls</span>
                </div>
                <div className="activity-meter">
                  <b style={{ width: `${Math.min(agent.occupancy, 100)}%` }} />
                </div>
                <dl>
                  <div><dt>Active</dt><dd>{formatDuration(agent.active_seconds)}</dd></div>
                  <div><dt>Talk</dt><dd>{formatDuration(agent.talk_seconds)}</dd></div>
                  <div><dt>Idle</dt><dd>{formatDuration(agent.idle_seconds)}</dd></div>
                  <div><dt>Occupancy</dt><dd>{agent.occupancy}%</dd></div>
                </dl>
              </div>
            ))}
          </div>
          <div className="pagination panel-pagination">
            <button type="button" disabled={activityPage <= 1} onClick={() => setActivityPage(activityPage - 1)}>
              Previous
            </button>
            <span>{activityPage} / {activityPages}</span>
            <button type="button" disabled={activityPage >= activityPages} onClick={() => setActivityPage(activityPage + 1)}>
              Next
            </button>
          </div>
        </Panel>
        <Panel title="Agent Efficiency">
          <div className="leaderboard">
            {visibleEfficiency.map((agent) => (
              <div className="leader-row" key={agent.agent}>
                <div>
                  <strong>{agent.agent_label || agent.agent}</strong>
                  <span>{agent.answered_calls}/{agent.total_calls} answered</span>
                </div>
                <b>{agent.efficiency_score}</b>
              </div>
            ))}
          </div>
          <div className="pagination panel-pagination">
            <button type="button" disabled={efficiencyPage <= 1} onClick={() => setEfficiencyPage(efficiencyPage - 1)}>
              Previous
            </button>
            <span>{efficiencyPage} / {efficiencyPages}</span>
            <button type="button" disabled={efficiencyPage >= efficiencyPages} onClick={() => setEfficiencyPage(efficiencyPage + 1)}>
              Next
            </button>
          </div>
        </Panel>
      </section>
      <section className="table-section">
        <div className="panel-head">
          <h2>Synced Agent Directory</h2>
          <span>{directory.length} saved agents</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Extension</th>
                <th>Name</th>
                <th>Voicemail</th>
                <th>Outbound CID</th>
                <th>Ring Timer</th>
                <th>Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {visibleDirectory.map((agent) => (
                <tr key={agent.extension}>
                  <td>{agent.extension}</td>
                  <td>{agent.name}</td>
                  <td>{agent.voicemail || "-"}</td>
                  <td>{agent.outbound_cid || "-"}</td>
                  <td>{agent.ringtimer || "-"}</td>
                  <td>{formatDateTime(agent.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <button type="button" disabled={directoryPage <= 1} onClick={() => setDirectoryPage(directoryPage - 1)}>
            Previous
          </button>
          <span>{directoryPage} / {directoryPages}</span>
          <button type="button" disabled={directoryPage >= directoryPages} onClick={() => setDirectoryPage(directoryPage + 1)}>
            Next
          </button>
        </div>
      </section>
    </>
  );
}

function CallSummary({ summary, agents, rowsPerPage }) {
  const perPage = rowsPerPage;
  const [page, setPage] = useState(1);
  const pages = Math.max(Math.ceil(agents.length / perPage), 1);

  useEffect(() => {
    setPage((current) => Math.min(current, pages));
  }, [pages]);

  const visibleAgents = pageSlice(agents, page, perPage);

  return (
    <>
      <section className="status-row">
        <Metric label="Received calls" value={summary.received_calls || 0} />
        <Metric label="Placed calls" value={summary.placed_calls || 0} />
        <Metric label="Answered" value={summary.answered_calls || 0} />
        <Metric label="Hung before answer" value={summary.hanged_before_received || 0} tone="warn" />
        <Metric label="Failed or busy" value={summary.failed_calls || 0} />
        <Metric label="Total duration" value={formatDuration(summary.total_duration_seconds)} />
      </section>
      <section className="table-section">
        <div className="panel-head">
          <h2>Agent Detail</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Score</th>
                <th>Calls</th>
                <th>Answered</th>
                <th>Missed</th>
                <th>Answer rate</th>
                <th>Occupancy</th>
                <th>Avg talk</th>
                <th>Avg ring</th>
              </tr>
            </thead>
            <tbody>
              {visibleAgents.map((agent) => (
                <tr key={agent.agent}>
                  <td>{agent.agent_label || agent.agent}</td>
                  <td><strong>{agent.efficiency_score}</strong></td>
                  <td>{agent.total_calls}</td>
                  <td>{agent.answered_calls}</td>
                  <td>{agent.missed_calls}</td>
                  <td>{agent.answer_rate}%</td>
                  <td>{agent.occupancy}%</td>
                  <td>{formatDuration(agent.avg_talk_seconds)}</td>
                  <td>{formatDuration(agent.avg_ring_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>{page} / {pages}</span>
          <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      </section>
    </>
  );
}

function UserAdmin({
  currentUser,
  users,
  newUser,
  setNewUser,
  onCreate,
  onUpdateUser,
  onChangePassword,
  onDeleteUser,
  setError,
  setMessage,
}) {
  const [menuOpenUserId, setMenuOpenUserId] = useState(null);
  const [viewUser, setViewUser] = useState(null);
  const [editingUser, setEditingUser] = useState(null);
  const [editForm, setEditForm] = useState({ full_name: "", enabled: true, new_password: "" });
  const [busyUserId, setBusyUserId] = useState(null);

  function openView(user) {
    setMenuOpenUserId(null);
    setViewUser(user);
  }

  function openEdit(user) {
    setMenuOpenUserId(null);
    setEditingUser(user);
    setEditForm({
      full_name: user.full_name || "",
      enabled: !!user.enabled,
      new_password: "",
    });
  }

  async function saveEdit() {
    if (!editingUser) return;
    setBusyUserId(editingUser.id);
    setError("");
    setMessage("");
    try {
      await onUpdateUser(editingUser.id, {
        username: editingUser.username,
        role: editingUser.role,
        full_name: editForm.full_name,
        enabled: editForm.enabled,
      });
      if (editForm.new_password.trim()) {
        await onChangePassword(editingUser.id, editForm.new_password.trim());
      }
      setMessage("User profile updated.");
      setEditingUser(null);
    } catch (err) {
      setError(err.message || "Could not update user");
    } finally {
      setBusyUserId(null);
    }
  }

  async function deleteUser() {
    if (!editingUser) return;
    if (currentUser.id === editingUser.id) {
      setError("You cannot delete your own account.");
      return;
    }
    const confirmed = window.confirm(`Delete user ${editingUser.username}?`);
    if (!confirmed) return;
    setBusyUserId(editingUser.id);
    setError("");
    setMessage("");
    try {
      await onDeleteUser(editingUser.id);
      setEditingUser(null);
      setMessage("User deleted.");
    } catch (err) {
      setError(err.message || "Could not delete user");
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <section className="admin-stack">
      <section className="panel">
        <div className="panel-head">
          <h2>Create User</h2>
        </div>
        <form className="user-form" onSubmit={onCreate}>
          <label>
            Full name
            <input value={newUser.full_name} onChange={(event) => setNewUser({ ...newUser, full_name: event.target.value })} />
          </label>
          <label>
            Username
            <input required value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} />
          </label>
          <label>
            Password
            <input required type="password" value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.target.value })} />
          </label>
          <label>
            Role
            <select value={newUser.role} onChange={(event) => setNewUser({ ...newUser, role: event.target.value })}>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <button type="submit">Create user</button>
        </form>
      </section>
      <section className="table-section">
        <div className="panel-head">
          <h2>Portal Users</h2>
          <span>{users.length} users</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Full name</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((portalUser) => (
                <tr key={portalUser.id}>
                  <td>{portalUser.username}</td>
                  <td>{portalUser.full_name}</td>
                  <td>{portalUser.role}</td>
                  <td>{portalUser.enabled ? "Enabled" : "Disabled"}</td>
                  <td>{formatDateTime(portalUser.last_login_at)}</td>
                  <td>
                    <div className="menu-wrap">
                      <button
                        type="button"
                        className="dots-button"
                        onClick={() => setMenuOpenUserId(menuOpenUserId === portalUser.id ? null : portalUser.id)}
                      >
                        ...
                      </button>
                      {menuOpenUserId === portalUser.id ? (
                        <div className="dots-menu">
                          <button type="button" onClick={() => openView(portalUser)}>View</button>
                          <button type="button" onClick={() => openEdit(portalUser)}>Edit</button>
                        </div>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {viewUser ? (
        <section className="modal-backdrop" onClick={() => setViewUser(null)}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <h2>User Profile</h2>
            </div>
            <dl className="profile-grid">
              <div><dt>Username</dt><dd>{viewUser.username}</dd></div>
              <div><dt>Full name</dt><dd>{viewUser.full_name}</dd></div>
              <div><dt>Role</dt><dd>{viewUser.role}</dd></div>
              <div><dt>Status</dt><dd>{viewUser.enabled ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Last login</dt><dd>{formatDateTime(viewUser.last_login_at) || "-"}</dd></div>
              <div><dt>Created</dt><dd>{formatDateTime(viewUser.created_at) || "-"}</dd></div>
            </dl>
            <div className="modal-actions">
              <button type="button" className="mini-button subtle" onClick={() => setViewUser(null)}>Close</button>
            </div>
          </div>
        </section>
      ) : null}

      {editingUser ? (
        <section className="modal-backdrop" onClick={() => setEditingUser(null)}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <h2>Edit User</h2>
            </div>
            <form className="user-form" onSubmit={(event) => {
              event.preventDefault();
              saveEdit();
            }}>
              <label>
                Username
                <input value={editingUser.username} disabled />
              </label>
              <label>
                Role
                <input value={editingUser.role} disabled />
              </label>
              <label>
                Full name
                <input
                  value={editForm.full_name}
                  onChange={(event) => setEditForm((current) => ({ ...current, full_name: event.target.value }))}
                />
              </label>
              <label>
                New password
                <input
                  type="password"
                  placeholder="Leave blank to keep current password"
                  value={editForm.new_password}
                  onChange={(event) => setEditForm((current) => ({ ...current, new_password: event.target.value }))}
                />
              </label>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={editForm.enabled}
                  onChange={(event) => setEditForm((current) => ({ ...current, enabled: event.target.checked }))}
                />
                <span>Enabled</span>
              </label>
              <div className="modal-actions">
                <button type="submit" className="mini-button" disabled={busyUserId === editingUser.id}>Save</button>
                <button type="button" className="mini-button subtle" onClick={() => setEditingUser(null)}>Cancel</button>
                <button
                  type="button"
                  className="mini-button danger"
                  disabled={busyUserId === editingUser.id || currentUser.id === editingUser.id}
                  onClick={deleteUser}
                >
                  Delete
                </button>
              </div>
            </form>
          </div>
        </section>
      ) : null}
    </section>
  );
}
