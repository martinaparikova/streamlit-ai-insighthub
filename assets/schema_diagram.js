export default function ({ parentElement, data }) {
  const root = parentElement.querySelector(".schema-root");
  const expanded = new Set(
    [...root.querySelectorAll("details[open]")].map(node => node.dataset.table)
  );
  const cs = data.language === "cs";
  const make = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const svgElement = (tag, attributes = {}) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
    return element;
  };
  const stage = make("div", "schema-stage");
  stage.setAttribute("role", "group");
  stage.setAttribute("aria-label", cs ? "Schéma tabulek a vztahů" : "Tables and relationships");
  const svg = svgElement("svg", { class: "schema-links", "aria-hidden": "true" });
  stage.append(svg);
  const tableNodes = new Map();
  const tables = [...data.tables].sort((a, b) => Number(b.id === data.hub) - Number(a.id === data.hub));
  const satelliteCount = Math.max(0, tables.length - 1);
  const rows = satelliteCount === 2 ? 2 : Math.max(1, Math.ceil(satelliteCount / 2));
  for (const [index, table] of tables.entries()) {
    const node = make("details", "schema-node");
    node.dataset.table = table.id;
    node.dataset.hub = String(table.id === data.hub);
    node.open = expanded.has(table.id);
    if (table.id === data.hub) {
      node.style.gridColumn = "3";
      node.style.gridRow = `1 / span ${rows}`;
      // Keep the hub's header in place when its columns expand.
      node.style.marginTop = tables.length > 1 ? `${(rows - 1) * 104 + 14}px` : "0";
    } else {
      const satellite = index - 1;
      node.style.gridColumn = satellite % 2 === 0 ? "1" : "5";
      node.style.gridRow = String(satellite % 2 === 0 ? Math.floor(satellite / 2) + 1 : rows - Math.floor(satellite / 2));
    }
    const summary = make("summary");
    summary.setAttribute("aria-label", `${table.name}: ${cs ? "zobrazit nebo skrýt sloupce" : "show or hide columns"}`);
    summary.append(make("strong", "schema-node-title", table.name));
    summary.append(make("span", "schema-node-technical", table.id));
    const preview = make("span", "schema-node-preview");
    for (const key of table.join_columns) preview.append(make("span", "schema-key", key));
    const count = table.columns.length;
    const countText = cs ? `${count} ${count === 1 ? "sloupec" : count < 5 ? "sloupce" : "sloupců"}` : `${count} ${count === 1 ? "column" : "columns"}`;
    preview.append(make("span", "schema-node-count", table.error ? (cs ? "Sloupce nedostupné" : "Columns unavailable") : countText));
    const chevron = svgElement("svg", { class: "schema-chevron", viewBox: "0 0 20 20", "aria-hidden": "true" });
    chevron.append(svgElement("path", { d: "m5 7 5 5 5-5", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    preview.append(chevron);
    summary.append(preview);
    node.append(summary);
    const columns = make("div", "schema-columns");
    columns.setAttribute("role", "list");
    columns.setAttribute("aria-label", cs ? "Sloupce tabulky" : "Table columns");
    if (table.error) {
      const error = make("div", "schema-error", `${cs ? "Metadata tabulky nelze načíst." : "Unable to load table metadata."} ${table.error}`);
      error.setAttribute("role", "alert");
      columns.append(error);
    }
    for (const column of table.columns) {
      const row = make("div", "schema-column");
      row.setAttribute("role", "listitem");
      row.dataset.key = String(table.join_columns.includes(column.name));
      const name = make("span", "schema-column-name", column.name);
      if (row.dataset.key === "true") name.title = cs ? "Sloupec propojení" : "Relationship column";
      row.append(name, make("span", "schema-column-type", column.type));
      columns.append(row);
    }
    if (table.description) columns.append(make("p", "schema-node-description", table.description));
    node.append(columns);
    stage.append(node);
    tableNodes.set(table.id, node);
  }
  const accessibleRelations = make("ul", "schema-relations");
  for (const relation of data.relationships) {
    accessibleRelations.append(make("li", "", `${relation.from_table}.${relation.from_column} → ${relation.to_table}.${relation.to_column} (${relation.cardinality})`));
  }
  root.replaceChildren(stage, accessibleRelations);
  let frame = 0;
  const draw = () => {
    frame = 0;
    const bounds = stage.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
    const definitions = svgElement("defs");
    const marker = svgElement("marker", { id: "schema-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "8", markerHeight: "8", orient: "auto" });
    marker.append(svgElement("path", { d: "M 1 1 L 9 5 L 1 9 Z", fill: "#c2185b" }));
    definitions.append(marker);
    svg.replaceChildren(definitions);
    const narrow = root.clientWidth <= 760;
    const hubBounds = tableNodes.get(data.hub).getBoundingClientRect();
    const pairs = data.relationships.map(relation => [relation.from_table, relation.to_table].sort().join("\0"));
    data.relationships.forEach((relation, index) => {
      const source = tableNodes.get(relation.from_table).getBoundingClientRect();
      const target = tableNodes.get(relation.to_table).getBoundingClientRect();
      const samePair = pairs.map((pair, position) => pair === pairs[index] ? position : -1).filter(position => position >= 0);
      const offset = (samePair.indexOf(index) - (samePair.length - 1) / 2) * 28;
      const sy = source.top - bounds.top + Math.max(14, Math.min(source.height - 14, 52 + offset));
      const ty = target.top - bounds.top + Math.max(14, Math.min(target.height - 14, 52 + offset));
      const verticalDirection = Math.sign(ty - sy) || 1;
      let path, labelX, labelY;
      if (narrow) {
        const sx = source.left - bounds.left;
        const tx = target.left - bounds.left;
        const lane = 22 + (index % 3) * 8;
        path = `M ${sx} ${sy} H ${lane + 8} Q ${lane} ${sy} ${lane} ${sy + verticalDirection * 8} V ${ty - verticalDirection * 24} C ${lane} ${ty - verticalDirection * 10}, ${tx - 24} ${ty - verticalDirection * 16}, ${tx} ${ty}`;
        labelX = lane;
        labelY = (sy + ty) / 2;
      } else {
        const goesRight = target.left > source.left;
        const sameColumn = Math.abs(source.left - target.left) < 2;
        if (sameColumn) {
          const onLeft = source.left < hubBounds.left;
          const sx = (onLeft ? source.right : source.left) - bounds.left;
          const tx = (onLeft ? target.right : target.left) - bounds.left;
          const lane = sx + (onLeft ? 32 : -32);
          path = `M ${sx} ${sy} C ${lane} ${sy}, ${lane} ${ty - verticalDirection * 18}, ${tx} ${ty}`;
          labelX = sx + (onLeft ? 24 : -24);
          labelY = (sy + ty) / 2;
        } else {
          const sx = (goesRight ? source.right : source.left) - bounds.left;
          const tx = (goesRight ? target.left : target.right) - bounds.left;
          const crossesHub = Math.min(source.right, target.right) < hubBounds.left
            && Math.max(source.left, target.left) > hubBounds.right;
          const middle = (sx + tx) / 2;
          if (crossesHub) {
            const direction = goesRight ? 1 : -1;
            const firstLane = sx + direction * 24;
            const lastLane = tx - direction * 24;
            const topLane = 14 + (index % 2) * 6;
            path = `M ${sx} ${sy} H ${firstLane} V ${topLane} H ${lastLane} V ${ty - verticalDirection * 22} C ${lastLane} ${ty - verticalDirection * 10}, ${tx - direction * 18} ${ty - verticalDirection * 14}, ${tx} ${ty}`;
            labelX = middle;
            labelY = topLane;
          } else {
            const horizontalPull = Math.max(24, Math.min(Math.abs(tx - sx) * 0.42, 96));
            const verticalPull = Math.max(10, Math.min(Math.abs(ty - sy) * 0.38, 56));
            path = `M ${sx} ${sy} C ${sx + (goesRight ? horizontalPull : -horizontalPull)} ${sy}, ${tx - (goesRight ? horizontalPull : -horizontalPull)} ${ty - verticalDirection * verticalPull}, ${tx} ${ty}`;
            labelX = middle;
            labelY = (sy + ty) / 2;
          }
        }
      }
      const group = svgElement("g", { "data-relationship": String(index) });
      group.append(svgElement("path", { class: "schema-link", d: path, "marker-end": "url(#schema-arrow)" }));
      group.append(svgElement("rect", { class: "schema-link-label", x: labelX - 20, y: labelY - 12, width: "40", height: "24", rx: "8" }));
      const text = svgElement("text", { class: "schema-link-text", x: labelX, y: labelY });
      text.textContent = relation.cardinality;
      group.append(text);
      svg.append(group);
    });
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(draw);
  };
  const observer = new ResizeObserver(schedule);
  observer.observe(stage);
  for (const node of tableNodes.values()) observer.observe(node);
  stage.addEventListener("toggle", schedule, true);
  schedule();
  return () => {
    observer.disconnect();
    stage.removeEventListener("toggle", schedule, true);
    cancelAnimationFrame(frame);
  };
}
