const COLLAPSE_PROPERTIES = new Set(["width", "transform"]);

export function completesPanelCollapse(
  expanded: boolean,
  propertyName: string,
  isPanelTransition: boolean,
): boolean {
  return !expanded && isPanelTransition && COLLAPSE_PROPERTIES.has(propertyName);
}
