"use client";

import { useState } from "react";

export default function CommunityMonitorPage() {
  const [lowBandwidth, setLowBandwidth] = useState(true);

  return (
    <main className="monitor-shell">
      <header className="monitor-header">
        <div>
          <p className="eyebrow">Community Monitor</p>
          <h1>Neighborhood Ecological Watch</h1>
        </div>
        <button className="toggle" onClick={() => setLowBandwidth((value) => !value)}>
          {lowBandwidth ? "Low-bandwidth: ON" : "Low-bandwidth: OFF"}
        </button>
      </header>

      <section className="mini-map">
        <div className="map-pin" />
        <div className="status-badge">3 new trees planted this month</div>
      </section>

      <section className="monitor-grid">
        <article className="panel">
          <h3>Recommended local action</h3>
          <p>Plant 12 native trees along the heat-vulnerable corridor near the community school.</p>
        </article>
        <article className="panel">
          <h3>Tree health</h3>
          <p>87% of monitored seedlings are healthy.</p>
        </article>
        <article className="panel upload-panel">
          <h3>Report a tree</h3>
          <input type="file" accept="image/*" capture="environment" />
          <button>Upload photo</button>
        </article>
      </section>
    </main>
  );
}
