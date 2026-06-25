export function connectedComponentIds(relationships = []) {
  const ids = new Set();
  relationships.forEach((relationship) => {
    if (relationship?.source_component_id) ids.add(relationship.source_component_id);
    if (relationship?.target_component_id) ids.add(relationship.target_component_id);
  });
  return ids;
}

export function filterExploreComponents(components = [], relationships = []) {
  const connected = connectedComponentIds(relationships);
  return components.filter((component) => connected.has(component.id));
}

export function buildExploreNeighborhood(nodeId, components = [], relationships = [], depth = 1) {
  if (!nodeId) return [];
  const maxDepth = Math.max(1, Math.min(Number(depth) || 1, 2));
  const componentById = new Map(components.map((component) => [component.id, component]));
  const adjacency = new Map();

  relationships.forEach((relationship) => {
    const source = relationship?.source_component_id;
    const target = relationship?.target_component_id;
    if (!source || !target) return;
    if (!adjacency.has(source)) adjacency.set(source, []);
    if (!adjacency.has(target)) adjacency.set(target, []);
    adjacency.get(source).push({ nodeId: target, relationship, direction: "out" });
    adjacency.get(target).push({ nodeId: source, relationship, direction: "in" });
  });

  const queue = [{ id: nodeId, depth: 0 }];
  const visited = new Set([nodeId]);
  const neighbors = [];

  while (queue.length > 0) {
    const current = queue.shift();
    if (current.depth >= maxDepth) continue;

    (adjacency.get(current.id) || []).forEach((edge) => {
      if (visited.has(edge.nodeId)) return;
      visited.add(edge.nodeId);
      const component = componentById.get(edge.nodeId);
      if (!component) return;
      const nextDepth = current.depth + 1;
      neighbors.push({
        ...component,
        depth: nextDepth,
        relationship_type: edge.relationship.relationship_type,
        relationship_label: (edge.relationship.display_label || edge.relationship.relationship_type || "related_to").replaceAll("_", " "),
        relationship_origin: edge.relationship.origin,
        relationship_confidence: edge.relationship.confidence,
        direction: edge.direction,
      });
      queue.push({ id: edge.nodeId, depth: nextDepth });
    });
  }

  return neighbors.sort((a, b) => a.depth - b.depth || String(a.name).localeCompare(String(b.name)));
}
