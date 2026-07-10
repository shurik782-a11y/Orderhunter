import { runMonitor } from "./channelMonitor.js";

function isAuthKeyDuplicated(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /AUTH_KEY_DUPLICATED/i.test(msg);
}

runMonitor().catch(async (e) => {
  console.error("[orderhunter] fatal", e);
  if (isAuthKeyDuplicated(e)) {
    // Avoid hammering Telegram / Railway restart storm
    console.error("[orderhunter] sleeping 120s before exit (AUTH_KEY_DUPLICATED)");
    await new Promise((r) => setTimeout(r, 120_000));
  }
  process.exit(1);
});
