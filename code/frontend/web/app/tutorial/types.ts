export type TutorialRecord = Record<string, unknown>;
export type ContractTutorialStage = "terms" | "preview" | "feedback" | "signed" | "legacy";

export interface TutorialStep {
  id: string;
  title: string;
  body: string;
  detail?: string;
  target: string;
  interactive?: boolean;
  optional?: boolean;
}

export interface TutorialDefinition {
  id: string;
  revision: number;
  title: string;
  steps: TutorialStep[];
  finishLabel?: string;
  finishFocusTarget?: string;
}

export interface TutorialContext {
  accountId: string;
  sessionId: string;
  entryKind: "new" | "load" | "review" | null;
  panel: string;
  readOnly: boolean;
  blocked: boolean;
  form: TutorialRecord | null;
  actions: TutorialRecord[];
  scene: string | null;
  contractStage?: ContractTutorialStage | null;
  contractId?: string;
}

export interface TutorialProgress {
  version: 1;
  auto: boolean;
  chapters: Record<string, { revision: number; status: "seen" | "completed"; step: number }>;
  paused?: { id: string; step: number };
}
