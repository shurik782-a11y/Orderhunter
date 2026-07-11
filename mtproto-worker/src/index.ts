import {
  AUTH_KEY_DUPLICATED_HELP,
  isAuthKeyDuplicated,
} from "./telegramClient.js";
import { runMonitor } from "./channelMonitor.js";

runMonitor().catch(async (e) => {
  console.error("[orderhunter] fatal", e);
  if (isAuthKeyDuplicated(e)) {
    console.error(AUTH_KEY_DUPLICATED_HELP);
    // Long pause so Railway does not thrash Telegram while you update the session.
    console.error(
      "[orderhunter] sleeping 300s before exit — replace TELEGRAM_USER_SESSION, then Redeploy",
    );
    await new Promise((r) => setTimeout(r, 300_000));
  }
  process.exit(1);
});
