/** Stable ordering: selected accounts first, without changing the query cache. */
export function activeFirst<T>(items: readonly T[], active: (item: T) => boolean): T[] {
  return [...items.filter(active), ...items.filter(item => !active(item))];
}
