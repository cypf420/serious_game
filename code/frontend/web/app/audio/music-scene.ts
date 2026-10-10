export type MusicScene = "none" | "main" | "night" | "broadcast" | "victory" | "defeat";

type MusicContext = {
  hasSession: boolean;
  nightConversationOpen: boolean;
  broadcastOpen: boolean;
  endingOpen: boolean;
  endingId: string;
};

const VICTORY_ENDINGS = new Set(["ending_22", "ending_23"]);

export function selectMusicScene(context: MusicContext): MusicScene {
  if (context.endingOpen && context.endingId) {
    return VICTORY_ENDINGS.has(context.endingId) ? "victory" : "defeat";
  }
  if (context.broadcastOpen) return "broadcast";
  if (context.nightConversationOpen) return "night";
  return context.hasSession ? "main" : "none";
}
