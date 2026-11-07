export interface TreemapItem {
  id: string;
  value: number;
}

export interface TreemapRect extends TreemapItem {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Squarified treemap (Bruls, Huizing, van Wijk): tiles stay close to square. */
export function squarify(items: TreemapItem[], width: number, height: number): TreemapRect[] {
  const positive = items.filter((item) => item.value > 0).sort((a, b) => b.value - a.value);
  const total = positive.reduce((sum, item) => sum + item.value, 0);
  if (total === 0 || width <= 0 || height <= 0) return [];

  const scale = (width * height) / total;
  const areas = positive.map((item) => ({ ...item, area: item.value * scale }));
  const rects: TreemapRect[] = [];
  let x = 0;
  let y = 0;
  let w = width;
  let h = height;
  let row: typeof areas = [];

  const worstRatio = (candidate: typeof areas) => {
    const side = Math.min(w, h);
    const sum = candidate.reduce((s, item) => s + item.area, 0);
    const largest = Math.max(...candidate.map((item) => item.area));
    const smallest = Math.min(...candidate.map((item) => item.area));
    return Math.max((side * side * largest) / (sum * sum), (sum * sum) / (side * side * smallest));
  };

  const layoutRow = () => {
    const sum = row.reduce((s, item) => s + item.area, 0);
    if (w >= h) {
      const rowWidth = sum / h;
      let offset = y;
      for (const { area, ...item } of row) {
        const tileHeight = area / rowWidth;
        rects.push({ ...item, x, y: offset, width: rowWidth, height: tileHeight });
        offset += tileHeight;
      }
      x += rowWidth;
      w -= rowWidth;
    } else {
      const rowHeight = sum / w;
      let offset = x;
      for (const { area, ...item } of row) {
        const tileWidth = area / rowHeight;
        rects.push({ ...item, x: offset, y, width: tileWidth, height: rowHeight });
        offset += tileWidth;
      }
      y += rowHeight;
      h -= rowHeight;
    }
    row = [];
  };

  for (const item of areas) {
    if (row.length === 0 || worstRatio([...row, item]) <= worstRatio(row)) {
      row.push(item);
    } else {
      layoutRow();
      row.push(item);
    }
  }
  if (row.length > 0) layoutRow();
  return rects;
}
