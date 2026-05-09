"use client";

import { useEffect, useMemo, useState } from "react";

function isoDate(date) {
  return date.toISOString().slice(0, 10);
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
  return { start: isoDate(start), end: isoDate(end), queue: "", agent: "" };
}

export default function Dashboard() {
  const [filters, setFilters] = useState(defaultFilters);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [activeView, setActiveView] = useState("overview");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const maxTrend = useMemo(() => {
    if (!data?.trend?.length) return 1;
    return Math.max(...data.trend.map((day) => day.calls), 1);
  }, [data]);

  const maxDurationBand = useMemo(() => {
    if (!data?.duration_bands?.length) return 1;
    return Math.max(...data.duration_bands.map((band) => band.calls), 1);
  }, [data]);

  async function loadDashboard(activeFilters = filters) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams(activeFilters);
    try {
      const response = await fetch(`/api/dashboard?${params.toString()}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `API returned ${response.status}`);
      setData(result);
    } catch (err) {
      setError(err.message || "Could not load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadDashboard(defaultFilters());
  }, []);

  function updateFilter(event) {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  function submit(event) {
    event.preventDefault();
    loadDashboard(filters);
  }

  async function syncFromPbx() {
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/sync?days=1", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `Sync returned ${response.status}`);
      setMessage(`Imported ${result.stored} calls from the PBX source.`);
      await loadDashboard(filters);
    } catch (err) {
      setError(err.message || "Could not sync from PBX");
    } finally {
      setSyncing(false);
    }
  }

  const totals = data?.totals || {};
  const summary = data?.summary || {};
  const agents = data?.agents || [];
  const recentCalls = data?.recent_calls || [];
  const hasData = !loading && Number(totals.total_calls || 0) > 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>PBX</span>
          <strong>Performance Portal</strong>
        </div>
        <nav>
          {[
            ["overview", "Dashboard"],
            ["calls", "Call Register"],
            ["agents", "Agent Activity"],
            ["summary", "Call Summary"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={activeView === key ? "nav-active" : ""}
              type="button"
              onClick={() => setActiveView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">FreePBX reporting store</p>
            <h1>Call center performance</h1>
          </div>
          <form className="filters" onSubmit={submit}>
            <label>
              Start
              <input type="date" name="start" value={filters.start} onChange={updateFilter} />
            </label>
            <label>
              End
              <input type="date" name="end" value={filters.end} onChange={updateFilter} />
            </label>
            <label>
              Queue
              <input type="text" name="queue" placeholder="sales" value={filters.queue} onChange={updateFilter} />
            </label>
            <label>
              Agent
              <input type="text" name="agent" placeholder="1001" value={filters.agent} onChange={updateFilter} />
            </label>
            <button type="submit" disabled={loading}>{loading ? "Loading" : "Refresh"}</button>
            <button type="button" className="secondary-button" disabled={syncing} onClick={syncFromPbx}>
              {syncing ? "Syncing" : "Sync PBX"}
            </button>
          </form>
        </header>

        <main>
          {error ? <div className="notice">{error}</div> : null}
          {message ? <div className="notice success">{message}</div> : null}
          {!hasData ? (
            <section className="empty-state">
              <h2>No real PBX records in the portal database</h2>
              <p>Configure the FreePBX database variables, run a sync, and this dashboard will populate from imported CDR rows.</p>
              <button type="button" onClick={syncFromPbx} disabled={syncing}>{syncing ? "Syncing" : "Sync PBX now"}</button>
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
                <Panel title="Call Volume Trend" detail={data?.source || ""}>
                  <div className="trend">
                    {(data?.trend || []).map((day) => {
                      const height = Math.max((day.calls / maxTrend) * 100, day.calls ? 5 : 0);
                      return (
                        <div className="bar-group" title={`${day.date}: ${day.calls} calls`} key={day.date}>
                          <div className="bar answered" style={{ height: `${height}%` }} />
                          <span>{day.date.slice(5)}</span>
                        </div>
                      );
                    })}
                  </div>
                </Panel>
                <Panel title="Duration Distribution">
                  <div className="horizontal-bars">
                    {(data?.duration_bands || []).map((band) => (
                      <div className="hbar-row" key={band.label}>
                        <span>{band.label}</span>
                        <div><b style={{ width: `${Math.max((band.calls / maxDurationBand) * 100, band.calls ? 4 : 0)}%` }} /></div>
                        <strong>{band.calls}</strong>
                      </div>
                    ))}
                  </div>
                </Panel>
              </section>

              <section className="dashboard-grid tight">
                <Ranking title="Top Call Sources" rows={data?.top_sources || []} />
                <Ranking title="Top Destinations" rows={data?.top_destinations || []} />
              </section>
            </>
          ) : null}

          {activeView === "calls" ? <CallRegister calls={recentCalls} /> : null}
          {activeView === "agents" ? <AgentActivity agents={data?.agent_activity || []} detail={agents} /> : null}
          {activeView === "summary" ? <CallSummary summary={summary} agents={agents} /> : null}
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

function CallRegister({ calls }) {
  return (
    <section className="table-section">
      <div className="panel-head">
        <h2>Call Register</h2>
        <span>Latest {calls.length} imported CDR rows</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Status</th>
              <th>Source</th>
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
    </section>
  );
}

function AgentActivity({ agents, detail }) {
  return (
    <section className="dashboard-grid">
      <Panel title="Agent Active Times">
        <div className="agent-list">
          {agents.map((agent) => (
            <div className="agent-card" key={agent.agent}>
              <div>
                <strong>{agent.agent}</strong>
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
      </Panel>
      <Panel title="Agent Efficiency">
        <div className="leaderboard">
          {detail.map((agent) => (
            <div className="leader-row" key={agent.agent}>
              <div>
                <strong>{agent.agent}</strong>
                <span>{agent.answered_calls}/{agent.total_calls} answered</span>
              </div>
              <b>{agent.efficiency_score}</b>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}

function CallSummary({ summary, agents }) {
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
              {agents.map((agent) => (
                <tr key={agent.agent}>
                  <td>{agent.agent}</td>
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
      </section>
    </>
  );
}
