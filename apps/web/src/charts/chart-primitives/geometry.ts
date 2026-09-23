export interface HitBox {
  id: string;
  kind: "zone" | "line" | "marker";
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Prefer markers, then lines, then filled zones when the pointer is inside more than one box. */
export function hitTestBoxes(boxes: readonly HitBox[], x: number, y: number): HitBox | null {
  let best: HitBox | null = null;
  let bestRank = Infinity;
  for (const box of boxes) {
    if (box.width < 0 || box.height < 0) continue;
    const inside = x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height;
    if (!inside) continue;
    const rank = box.kind === "marker" ? 0 : box.kind === "line" ? 1 : 2;
    if (rank < bestRank) {
      best = box;
      bestRank = rank;
    }
  }
  return best;
}

export function boxAroundPoint(id: string, x: number, y: number, radius: number): HitBox {
  return {
    id,
    kind: "marker",
    x: x - radius,
    y: y - radius,
    width: radius * 2,
    height: radius * 2,
  };
}
