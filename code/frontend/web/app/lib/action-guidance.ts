/** Optional server-issued directions. These never establish eligibility or write state. */
export type NextStep = {
  label: string;
  action_id?: string;
  variant_id?: string;
  target_ids?: string[];
  archive_id?: string;
  unavailable_reason?: string;
};

type RecordValue = Record<string, unknown>;
const records = (value: unknown): RecordValue[] => Array.isArray(value)
  ? value.filter((item): item is RecordValue => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];

export function nextSteps(value: unknown): NextStep[] {
  return records(value).filter(item => typeof item.label === "string" && item.label.trim()).map(item => ({
    label: String(item.label),
    ...Object.fromEntries(["action_id", "variant_id", "archive_id", "unavailable_reason"].flatMap(key => typeof item[key] === "string" ? [[key, item[key]]] : [])),
    ...(Array.isArray(item.target_ids) ? { target_ids: item.target_ids.filter((id): id is string => typeof id === "string") } : {}),
  }));
}

export function actionForNextStep(data: RecordValue, step: NextStep): RecordValue | null {
  if (!step.action_id || step.unavailable_reason) return null;
  const family = records(data.actions || data.items).find(item => item.action_id === step.action_id);
  if (!family) return null;
  const variants = records(family.variants);
  const choices = variants.filter(item => !step.variant_id || item.variant_id === step.variant_id);
  // Ambiguous guidance must not silently pick a different operation.
  if (choices.length !== 1) return null;
  const descriptor: RecordValue = { ...family, ...choices[0], action_id: family.action_id };
  const targets = records(descriptor.target_choices);
  if (step.archive_id && !targets.some(item => (item.archive_id || item.target_id || item.id) === step.archive_id)) return null;
  if (step.target_ids?.some(id => !targets.some(item => (item.target_id || item.id) === id))) return null;
  return {
    ...descriptor,
    ...(step.archive_id ? { preselected_archive_ids: [step.archive_id] } : {}),
    ...(step.target_ids?.length ? { preselected_npc_ids: step.target_ids } : {}),
  };
}
