import { runMonitor } from "./channelMonitor.js";

runMonitor().catch((e) => {
  console.error("[orderhunter] fatal", e);
  process.exit(1);
});
