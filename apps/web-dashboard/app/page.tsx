"use client";

import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

const LAGOS_CENTER = [3.3792, 6.5244] as [number, number];

export default function HomePage() {
  const mapContainer = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "demo_token";

    if (!mapContainer.current) return;

    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: LAGOS_CENTER,
      zoom: 11,
    });

    map.on("load", () => {
      map.addSource("planting-zones", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: {
                type: "Polygon",
                coordinates: [
                  [
                    [3.355, 6.517],
                    [3.385, 6.517],
                    [3.385, 6.545],
                    [3.355, 6.545],
                    [3.355, 6.517],
                  ],
                ],
              },
              properties: { name: "Priority planting zone" },
            },
          ],
        },
      });

      map.addLayer({
        id: "planting-zones-layer",
        type: "fill",
        source: "planting-zones",
        paint: {
          "fill-color": "#22c55e",
          "fill-opacity": 0.35,
        },
      });
    });

    return () => map.remove();
  }, []);

  return (
    <main className="page-shell">
      <aside className="sidebar">
        <p className="eyebrow">Planner Dashboard</p>
        <h1>Env-AI-Ron</h1>
        <p className="subtitle">Nature-Centred AI for regenerative urban ecosystems.</p>

        <div className="stat-card">
          <span>Projected canopy gain</span>
          <strong>+16.5% in 10 years</strong>
        </div>
        <div className="stat-card">
          <span>Cooling benefit</span>
          <strong>1.2°C reduction</strong>
        </div>
        <div className="stat-card">
          <span>Native species</span>
          <strong>50 recommended trees</strong>
        </div>
      </aside>

      <section className="map-panel">
        <div ref={mapContainer} className="map-container" />
      </section>
    </main>
  );
}
