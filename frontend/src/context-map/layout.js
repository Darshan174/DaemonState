export const MAP_WIDTH = 1000;
export const MAP_HEIGHT = 620;
export const MAP_NODE_SIZE = { width: 124, height: 58 };

const NODE_GAP = { x: 12, y: 10 };
const ZONE_CONTENT_INSET = { top: 26, right: 7, bottom: 8, left: 7 };

export const MAP_LANE_LIMITS = {
  sessions: 6,
  architecture: 8,
  decisions: 4,
  next_tasks: 2,
  prs: 4,
  issues: 4,
  documents: 2,
  other: 2,
};

export const MAP_ZONES = {
  sessions: { label: "AI sessions", x: 26, y: 56, width: 274, height: 230 },
  architecture: { label: "System", emptyLabel: "Refresh this project to map its structure.", x: 330, y: 56, width: 338, height: 360 },
  decisions: { label: "Direction", emptyLabel: "No current verified decisions.", x: 26, y: 310, width: 274, height: 160 },
  next_tasks: { label: "Next", emptyLabel: "No explicit verified next task.", x: 26, y: 494, width: 274, height: 110 },
  prs: { label: "Delivery", x: 700, y: 56, width: 274, height: 180 },
  issues: { label: "Risks", x: 700, y: 270, width: 274, height: 180 },
  documents: { label: "Docs", emptyLabel: "No verified document gaps.", x: 330, y: 440, width: 162, height: 170 },
  other: { label: "Evidence", x: 506, y: 440, width: 162, height: 170 },
};

export function positionNodes(projection) {
  return projection.lanes.flatMap((lane) => {
    const zone = MAP_ZONES[lane.id] || MAP_ZONES.other;
    const count = lane.cards.length;
    if (!count) return [];
    const contentWidth = zone.width - ZONE_CONTENT_INSET.left - ZONE_CONTENT_INSET.right;
    const contentHeight = zone.height - ZONE_CONTENT_INSET.top - ZONE_CONTENT_INSET.bottom;
    const maxColumns = Math.max(1, Math.floor(
      (contentWidth + NODE_GAP.x) / (MAP_NODE_SIZE.width + NODE_GAP.x),
    ));
    const columns = Math.min(count, maxColumns);
    const rows = Math.ceil(count / columns);
    const gridWidth = columns * MAP_NODE_SIZE.width + (columns - 1) * NODE_GAP.x;
    const gridHeight = rows * MAP_NODE_SIZE.height + (rows - 1) * NODE_GAP.y;
    const startX = zone.x + ZONE_CONTENT_INSET.left + (contentWidth - gridWidth) / 2 + MAP_NODE_SIZE.width / 2;
    const startY = zone.y + ZONE_CONTENT_INSET.top + (contentHeight - gridHeight) / 2 + MAP_NODE_SIZE.height / 2;
    return lane.cards.map((card, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      return {
        id: card.id,
        card,
        laneId: lane.id,
        x: startX + column * (MAP_NODE_SIZE.width + NODE_GAP.x),
        y: startY + row * (MAP_NODE_SIZE.height + NODE_GAP.y),
      };
    });
  });
}
