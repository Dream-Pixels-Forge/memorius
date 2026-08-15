"""Knowledge Graph Visualizer for memorius.

Generates a standalone, zero-dependency, interactive HTML/JS force-directed
graph visualizer to explore associative memory connections, clusters, and
contradictions offline or in the browser.
"""

from __future__ import annotations

import json
from typing import Any


def render_graph_html(
    graph_data: dict[str, Any],
    title: str = "Memorius Knowledge Graph",
) -> str:
    """Render an interactive, self-contained HTML visualization of the graph.

    Args:
        graph_data: Dict with 'nodes', 'edges', and 'summary' keys.
        title: Page title.

    Returns:
        Full HTML string ready to serve or write to disk.
    """
    json_payload = json.dumps(graph_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg-primary: #0a0c14;
    --bg-surface: #121624;
    --bg-card: #181f33;
    --border-color: #242e4c;
    --border-bright: #3a4b7c;
    --text-primary: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent-cyan: #06b6d4;
    --accent-indigo: #818cf8;
    --accent-purple: #a855f7;
    --accent-amber: #f59e0b;
    --accent-rose: #f43f5e;
    --accent-emerald: #10b981;
    --shadow-glow: 0 0 25px rgba(6, 182, 212, 0.15);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    user-select: none;
    -webkit-user-select: none;
  }}

  body {{
    background-color: var(--bg-primary);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    overflow: hidden;
    width: 100vw;
    height: 100vh;
  }}

  /* Top Bar */
  header {{
    position: absolute;
    top: 16px;
    left: 20px;
    right: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    pointer-events: none;
    z-index: 20;
  }}

  .brand-group {{
    display: flex;
    align-items: center;
    gap: 12px;
    background: rgba(18, 22, 36, 0.85);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    padding: 8px 16px;
    border-radius: 12px;
    pointer-events: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }}

  .brand-logo {{
    width: 28px;
    height: 28px;
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-indigo));
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 14px;
    color: #fff;
    box-shadow: 0 0 12px rgba(6, 182, 212, 0.4);
  }}

  .brand-title {{
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--text-primary);
  }}

  .stats-pill {{
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-card);
    padding: 3px 8px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
  }}

  .header-actions {{
    display: flex;
    gap: 10px;
    pointer-events: auto;
  }}

  /* Control Panel Toolbar */
  .toolbar {{
    position: absolute;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(18, 22, 36, 0.85);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    padding: 8px 16px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    gap: 12px;
    z-index: 20;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  }}

  .btn {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 6px 12px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
  }}

  .btn:hover {{
    background: #242e4c;
    color: var(--text-primary);
    border-color: var(--border-bright);
  }}

  .btn.active {{
    background: var(--accent-cyan);
    color: #04131f;
    border-color: var(--accent-cyan);
  }}

  /* Search & Filter Bar */
  .search-box {{
    display: flex;
    align-items: center;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 4px 10px;
    width: 200px;
    transition: all 0.2s ease;
  }}

  .search-box:focus-within {{
    border-color: var(--accent-cyan);
    box-shadow: 0 0 10px rgba(6, 182, 212, 0.3);
    width: 260px;
  }}

  .search-box input {{
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-primary);
    font-size: 13px;
    width: 100%;
    user-select: text;
    -webkit-user-select: text;
  }}

  .search-box input::placeholder {{
    color: var(--text-muted);
  }}

  select.filter-select {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    padding: 6px 10px;
    border-radius: 8px;
    font-size: 13px;
    outline: none;
    cursor: pointer;
  }}

  select.filter-select:hover {{
    border-color: var(--border-bright);
    color: var(--text-primary);
  }}

  /* Canvas */
  #graph-canvas {{
    display: block;
    width: 100%;
    height: 100%;
    cursor: grab;
  }}

  #graph-canvas:active {{
    cursor: grabbing;
  }}

  /* Legend */
  .legend-card {{
    position: absolute;
    bottom: 20px;
    left: 20px;
    background: rgba(18, 22, 36, 0.85);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--text-secondary);
    z-index: 20;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}

  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .legend-line {{
    width: 20px;
    height: 3px;
    border-radius: 2px;
  }}

  /* Sidebar Inspector */
  .inspector-sidebar {{
    position: absolute;
    top: 20px;
    right: 20px;
    bottom: 20px;
    width: 360px;
    background: rgba(18, 22, 36, 0.95);
    backdrop-filter: blur(16px);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    box-shadow: -10px 0 30px rgba(0,0,0,0.5);
    display: flex;
    flex-direction: column;
    transform: translateX(390px);
    transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 30;
    overflow: hidden;
  }}

  .inspector-sidebar.open {{
    transform: translateX(0);
  }}

  .inspector-header {{
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }}

  .inspector-title {{
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.3;
    word-break: break-word;
  }}

  .close-btn {{
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 20px;
    cursor: pointer;
    padding: 0 4px;
  }}
  .close-btn:hover {{
    color: var(--text-primary);
  }}

  .inspector-body {{
    padding: 16px 20px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    user-select: text;
    -webkit-user-select: text;
  }}

  .meta-tag-group {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}

  .badge {{
    font-size: 11px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .badge-path {{
    background: #1e293b;
    color: var(--accent-cyan);
    border: 1px solid #334155;
  }}

  .badge-contradicts {{
    background: rgba(244, 63, 94, 0.15);
    color: var(--accent-rose);
    border: 1px solid rgba(244, 63, 94, 0.3);
  }}

  .content-box {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-primary);
    white-space: pre-wrap;
    max-height: 240px;
    overflow-y: auto;
  }}

  .connected-list {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}

  .connected-item {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
  }}

  .connected-item:hover {{
    border-color: var(--accent-cyan);
    background: #1f2740;
  }}

  /* Tooltip */
  #tooltip {{
    position: absolute;
    display: none;
    background: rgba(18, 22, 36, 0.95);
    backdrop-filter: blur(10px);
    border: 1px solid var(--border-bright);
    color: var(--text-primary);
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 12px;
    pointer-events: none;
    z-index: 50;
    max-width: 260px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
  }}
</style>
</head>
<body>

<header>
  <div class="brand-group">
    <div class="brand-logo">M</div>
    <div class="brand-title">Knowledge Graph</div>
    <div class="stats-pill" id="stats-pill">Loading...</div>
  </div>

  <div class="header-actions">
    <div class="search-box">
      <input type="text" id="search-input" placeholder="Search memories...">
    </div>
    <select class="filter-select" id="shelf-select">
      <option value="all">All Shelves</option>
    </select>
    <select class="filter-select" id="relation-select">
      <option value="all">All Relations</option>
      <option value="related">Related</option>
      <option value="references">References</option>
      <option value="contradicts">Contradicts</option>
      <option value="co_occurs">Co-occurs</option>
    </select>
  </div>
</header>

<div class="toolbar">
  <button class="btn" id="reset-view-btn">🎯 Center</button>
  <button class="btn" id="pause-btn">⏸ Pause</button>
  <button class="btn active" id="labels-btn">🏷 Labels</button>
</div>

<div class="legend-card">
  <div style="font-weight: 700; color: var(--text-primary); margin-bottom: 2px;">Edge Types</div>
  <div class="legend-item"><div class="legend-line" style="background: var(--accent-cyan);"></div> Related</div>
  <div class="legend-item"><div class="legend-line" style="background: var(--accent-indigo);"></div> References</div>
  <div class="legend-item"><div class="legend-line" style="background: var(--accent-rose); border-bottom: 1px dashed;"></div> Contradicts</div>
  <div class="legend-item"><div class="legend-line" style="background: var(--accent-amber); border-bottom: 2px dotted;"></div> Co-occurs</div>
</div>

<div class="inspector-sidebar" id="inspector">
  <div class="inspector-header">
    <div class="inspector-title" id="insp-title">Memory Details</div>
    <button class="close-btn" id="close-inspector">&times;</button>
  </div>
  <div class="inspector-body">
    <div class="meta-tag-group" id="insp-badges"></div>
    <div>
      <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase;">Content</div>
      <div class="content-box" id="insp-content"></div>
    </div>
    <div>
      <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase;">Connected Memories (<span id="insp-conn-count">0</span>)</div>
      <ul class="connected-list" id="insp-connections"></ul>
    </div>
  </div>
</div>

<div id="tooltip"></div>
<canvas id="graph-canvas"></canvas>

<script>
(function() {{
  const rawData = {json_payload};
  const nodes = rawData.nodes || [];
  const edges = rawData.edges || [];

  // DOM elements
  const canvas = document.getElementById("graph-canvas");
  const ctx = canvas.getContext("2d");
  const statsPill = document.getElementById("stats-pill");
  const searchInput = document.getElementById("search-input");
  const shelfSelect = document.getElementById("shelf-select");
  const relationSelect = document.getElementById("relation-select");
  const resetBtn = document.getElementById("reset-view-btn");
  const pauseBtn = document.getElementById("pause-btn");
  const labelsBtn = document.getElementById("labels-btn");
  const inspector = document.getElementById("inspector");
  const closeInspBtn = document.getElementById("close-inspector");
  const tooltip = document.getElementById("tooltip");

  // State
  let showLabels = true;
  let isSimulating = true;
  let selectedNode = null;
  let hoveredNode = null;
  let searchQuery = "";
  let selectedShelf = "all";
  let selectedRelation = "all";

  // Camera viewport
  let transform = {{ x: 0, y: 0, scale: 1 }};
  let isDraggingCanvas = false;
  let dragStart = {{ x: 0, y: 0 }};
  let draggedNode = null;

  // Palette generator for shelves
  const shelfColors = [
    "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    "#10b981", "#f59e0b", "#14b8a6", "#6366f1"
  ];
  const shelfColorMap = {{}};
  const shelves = new Set();

  nodes.forEach((n, idx) => {{
    shelves.add(n.shelf);
    if (!shelfColorMap[n.shelf]) {{
      shelfColorMap[n.shelf] = shelfColors[Object.keys(shelfColorMap).length % shelfColors.length];
    }}
    // Initialize node physics
    const angle = (idx / (nodes.length || 1)) * Math.PI * 2;
    const radius = 80 + Math.random() * 250;
    n.x = Math.cos(angle) * radius;
    n.y = Math.sin(angle) * radius;
    n.vx = 0;
    n.vy = 0;
    n.radius = Math.max(7, Math.min(22, 6 + (n.degree || 1) * 2.5 + Math.min(n.access_count || 0, 5)));
  }});

  // Populate shelf filter
  shelves.forEach(s => {{
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = `Shelf: ${{s}}`;
    shelfSelect.appendChild(opt);
  }});

  // Index nodes
  const nodeMap = new Map();
  nodes.forEach(n => nodeMap.set(n.id, n));

  // Resolved edges with node references
  const resolvedEdges = edges.map(e => ({{
    source: nodeMap.get(e.source),
    target: nodeMap.get(e.target),
    weight: e.weight || 1.0,
    relation: e.relation || "related"
  }})).filter(e => e.source && e.target);

  // Update Stats
  statsPill.textContent = `${{nodes.length}} nodes · ${{resolvedEdges.length}} edges`;

  // Window resize
  function resizeCanvas() {{
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    if (transform.x === 0 && transform.y === 0) {{
      transform.x = canvas.width / 2;
      transform.y = canvas.height / 2;
    }}
  }}
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  // Color mapping for relations
  function getEdgeColor(relation) {{
    switch (relation) {{
      case "contradicts": return "#f43f5e";
      case "references": return "#818cf8";
      case "co_occurs": return "#f59e0b";
      default: return "#06b6d4";
    }}
  }}

  // Filter check
  function isNodeVisible(n) {{
    if (selectedShelf !== "all" && n.shelf !== selectedShelf) return false;
    if (searchQuery) {{
      const q = searchQuery.toLowerCase();
      const matchLabel = (n.label || "").toLowerCase().includes(q);
      const matchContent = (n.content || "").toLowerCase().includes(q);
      const matchTags = (n.tags || []).some(t => String(t).toLowerCase().includes(q));
      if (!matchLabel && !matchContent && !matchTags) return false;
    }}
    return true;
  }}

  function isEdgeVisible(e) {{
    if (!isNodeVisible(e.source) || !isNodeVisible(e.target)) return false;
    if (selectedRelation !== "all" && e.relation !== selectedRelation) return false;
    return true;
  }}

  // Simulation step (Barnes-Hut / Force layout)
  function tickSimulation() {{
    if (!isSimulating) return;

    const visibleNodes = nodes.filter(isNodeVisible);
    const repulsion = 450;
    const centerAttract = 0.015;
    const damping = 0.88;

    // Node repulsion
    for (let i = 0; i < visibleNodes.length; i++) {{
      const n1 = visibleNodes[i];
      for (let j = i + 1; j < visibleNodes.length; j++) {{
        const n2 = visibleNodes[j];
        let dx = n2.x - n1.x;
        let dy = n2.y - n1.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 400) {{
          const force = (repulsion / (dist * dist));
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          if (n1 !== draggedNode) {{ n1.vx -= fx; n1.vy -= fy; }}
          if (n2 !== draggedNode) {{ n2.vx += fx; n2.vy += fy; }}
        }}
      }}
    }}

    // Edge attraction (springs)
    resolvedEdges.forEach(e => {{
      if (!isEdgeVisible(e)) return;
      let dx = e.target.x - e.source.x;
      let dy = e.target.y - e.source.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      let targetDist = e.relation === "contradicts" ? 140 : 80;
      let force = (dist - targetDist) * 0.035 * (e.weight || 1.0);
      let fx = (dx / dist) * force;
      let fy = (dy / dist) * force;

      if (e.source !== draggedNode) {{ e.source.vx += fx; e.source.vy += fy; }}
      if (e.target !== draggedNode) {{ e.target.vx -= fx; e.target.vy -= fy; }}
    }});

    // Center gravity & update position
    visibleNodes.forEach(n => {{
      if (n === draggedNode) return;
      n.vx -= n.x * centerAttract;
      n.vy -= n.y * centerAttract;
      n.vx *= damping;
      n.vy *= damping;
      n.x += n.vx;
      n.y += n.vy;
    }});
  }}

  // Render loop
  function draw() {{
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.scale, transform.scale);

    // Draw Edges
    resolvedEdges.forEach(e => {{
      if (!isEdgeVisible(e)) return;

      const isConnectedToSelected = selectedNode && (e.source === selectedNode || e.target === selectedNode);
      const isConnectedToHovered = hoveredNode && (e.source === hoveredNode || e.target === hoveredNode);
      const isHighlighted = isConnectedToSelected || isConnectedToHovered;

      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);

      ctx.strokeStyle = getEdgeColor(e.relation);
      ctx.lineWidth = isHighlighted ? 2.5 : Math.max(1, (e.weight || 1.0) * 1.5);
      ctx.globalAlpha = isHighlighted ? 0.95 : (selectedNode ? 0.15 : 0.45);

      if (e.relation === "contradicts") {{
        ctx.setLineDash([6, 4]);
      }} else if (e.relation === "co_occurs") {{
        ctx.setLineDash([2, 3]);
      }} else {{
        ctx.setLineDash([]);
      }}

      ctx.stroke();
      ctx.setLineDash([]);
    }});

    // Draw Nodes
    nodes.forEach(n => {{
      if (!isNodeVisible(n)) return;

      const isSelected = n === selectedNode;
      const isHovered = n === hoveredNode;
      const isConnectedToSelected = selectedNode && resolvedEdges.some(
        e => isEdgeVisible(e) && ((e.source === selectedNode && e.target === n) || (e.target === selectedNode && e.source === n))
      );
      const isDimmed = selectedNode && !isSelected && !isConnectedToSelected;

      const color = shelfColorMap[n.shelf] || "#06b6d4";

      // Outer glow for selected/hovered
      if (isSelected || isHovered) {{
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.25;
        ctx.fill();
      }}

      // Node Body
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = isDimmed ? 0.2 : 0.9;
      ctx.fill();

      // Node Ring border
      ctx.lineWidth = isSelected ? 2.5 : 1.5;
      ctx.strokeStyle = isSelected ? "#ffffff" : "#0a0c14";
      ctx.globalAlpha = isDimmed ? 0.3 : 1.0;
      ctx.stroke();

      // Node Labels
      if (showLabels || isSelected || isHovered) {{
        ctx.font = `${{isSelected ? "bold 13px" : "11px"}} sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = isSelected ? "#ffffff" : "#cbd5e1";
        ctx.globalAlpha = isDimmed ? 0.2 : 0.95;
        ctx.fillText(n.note || n.label, n.x, n.y + n.radius + 14);
      }}
    }});

    ctx.restore();
  }}

  function loop() {{
    tickSimulation();
    draw();
    requestAnimationFrame(loop);
  }}
  requestAnimationFrame(loop);

  // Screen to graph space
  function screenToGraph(sx, sy) {{
    return {{
      x: (sx - transform.x) / transform.scale,
      y: (sy - transform.y) / transform.scale
    }};
  }}

  // Find node at point
  function getNodeAt(x, y) {{
    const pt = screenToGraph(x, y);
    for (let i = nodes.length - 1; i >= 0; i--) {{
      const n = nodes[i];
      if (!isNodeVisible(n)) continue;
      const dx = pt.x - n.x;
      const dy = pt.y - n.y;
      if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 4) {{
        return n;
      }}
    }}
    return null;
  }}

  // Inspector details
  function openInspector(node) {{
    selectedNode = node;
    document.getElementById("insp-title").textContent = `${{node.shelf}} / ${{node.note}}`;

    const badgesContainer = document.getElementById("insp-badges");
    badgesContainer.innerHTML = `
      <span class="badge badge-path">${{node.vault}}</span>
      <span class="badge badge-path">${{node.shelf}}</span>
      <span class="badge" style="background: ${{shelfColorMap[node.shelf] || '#06b6d4'}}; color: #04131f;">${{node.category}}</span>
      ${{(node.tags || []).map(t => `<span class="badge" style="background: #1e293b; color: #94a3b8;">#${{t}}</span>`).join('')}}
    `;

    document.getElementById("insp-content").textContent = node.content || "(No content)";

    const connList = document.getElementById("insp-connections");
    connList.innerHTML = "";

    const connectedEdges = resolvedEdges.filter(e => e.source === node || e.target === node);
    document.getElementById("insp-conn-count").textContent = connectedEdges.length;

    connectedEdges.forEach(e => {{
      const other = e.source === node ? e.target : e.source;
      const li = document.createElement("li");
      li.className = "connected-item";
      li.innerHTML = `
        <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
          <span style="font-weight: 600; color: var(--text-primary);">${{other.note}}</span>
          <span style="color: ${{getEdgeColor(e.relation)}}; font-weight: 700; text-transform: uppercase; font-size: 10px;">${{e.relation}}</span>
        </div>
        <div style="color: var(--text-muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${{other.snippet}}</div>
      `;
      li.addEventListener("click", () => {{
        openInspector(other);
      }});
      connList.appendChild(li);
    }});

    inspector.classList.add("open");
  }}

  function closeInspector() {{
    selectedNode = null;
    inspector.classList.remove("open");
  }}
  closeInspBtn.addEventListener("click", closeInspector);

  // Mouse / Touch Event handlers
  canvas.addEventListener("mousedown", (e) => {{
    const node = getNodeAt(e.clientX, e.clientY);
    if (node) {{
      draggedNode = node;
      openInspector(node);
    }} else {{
      isDraggingCanvas = true;
      dragStart.x = e.clientX - transform.x;
      dragStart.y = e.clientY - transform.y;
    }}
  }});

  canvas.addEventListener("mousemove", (e) => {{
    const node = getNodeAt(e.clientX, e.clientY);
    hoveredNode = node;

    if (draggedNode) {{
      const pt = screenToGraph(e.clientX, e.clientY);
      draggedNode.x = pt.x;
      draggedNode.y = pt.y;
      draggedNode.vx = 0;
      draggedNode.vy = 0;
      tooltip.style.display = "none";
    }} else if (isDraggingCanvas) {{
      transform.x = e.clientX - dragStart.x;
      transform.y = e.clientY - dragStart.y;
      tooltip.style.display = "none";
    }} else if (hoveredNode) {{
      tooltip.style.display = "block";
      tooltip.style.left = (e.clientX + 14) + "px";
      tooltip.style.top = (e.clientY + 14) + "px";
      tooltip.innerHTML = `
        <div style="font-weight: 700; color: var(--text-primary); margin-bottom: 2px;">${{hoveredNode.note}}</div>
        <div style="color: var(--accent-cyan); font-size: 11px; margin-bottom: 4px;">${{hoveredNode.shelf}} &middot; ${{hoveredNode.category}}</div>
        <div style="color: var(--text-secondary); font-size: 11px;">${{hoveredNode.snippet}}</div>
      `;
    }} else {{
      tooltip.style.display = "none";
    }}
  }});

  window.addEventListener("mouseup", () => {{
    isDraggingCanvas = false;
    draggedNode = null;
  }});

  // Zoom
  canvas.addEventListener("wheel", (e) => {{
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const newScale = Math.max(0.15, Math.min(5.0, transform.scale * zoomFactor));

    const mousePt = {{ x: e.clientX, y: e.clientY }};
    transform.x = mousePt.x - (mousePt.x - transform.x) * (newScale / transform.scale);
    transform.y = mousePt.y - (mousePt.y - transform.y) * (newScale / transform.scale);
    transform.scale = newScale;
  }}, {{ passive: false }});

  // Filter Event Listeners
  searchInput.addEventListener("input", (e) => {{
    searchQuery = e.target.value.trim();
  }});

  shelfSelect.addEventListener("change", (e) => {{
    selectedShelf = e.target.value;
  }});

  relationSelect.addEventListener("change", (e) => {{
    selectedRelation = e.target.value;
  }});

  resetBtn.addEventListener("click", () => {{
    transform.x = canvas.width / 2;
    transform.y = canvas.height / 2;
    transform.scale = 1;
  }});

  pauseBtn.addEventListener("click", () => {{
    isSimulating = !isSimulating;
    pauseBtn.textContent = isSimulating ? "⏸ Pause" : "▶ Resume";
    pauseBtn.classList.toggle("active", !isSimulating);
  }});

  labelsBtn.addEventListener("click", () => {{
    showLabels = !showLabels;
    labelsBtn.classList.toggle("active", showLabels);
  }});

}})();
</script>
</body>
</html>
"""
