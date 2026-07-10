import { loadChannels, postToBackend, extractContactHint } from "./backendBridge.js";
import { ENV } from "./env.js";
import { getFullClient } from "./telegramClient.js";

const seen = new Set<string>();

function messageKey(channel: string, id: number): string {
  return `${channel}:${id}`;
}

export async function pollChannelsOnce(): Promise<void> {
  const channels = loadChannels();
  if (!channels.length) {
    console.warn("[orderhunter] no enabled channels in config");
    return;
  }

  const client = await getFullClient();
  for (const ch of channels) {
    const username = ch.username.replace(/^@/, "");
    try {
      const entity = await client.getEntity(username);
      for await (const msg of client.iterMessages(entity, { limit: 15 })) {
        if (!msg.id || msg.out) continue;
        const key = messageKey(username, msg.id);
        if (seen.has(key)) continue;
        seen.add(key);
        const text = msg.message || "";
        if (text.length < 40) continue;
        const url = `https://t.me/${username}/${msg.id}`;
        await postToBackend({
          message_id: msg.id,
          channel: username,
          text,
          url,
          contact_hint: extractContactHint(text),
        });
        console.log(`[orderhunter] ingested ${username}/${msg.id}`);
      }
    } catch (e) {
      console.error(`[orderhunter] channel ${username} failed`, e);
    }
  }
}

export async function startRealtimeListener(): Promise<void> {
  const channels = loadChannels();
  const usernames = channels.map((c) => c.username.replace(/^@/, ""));
  if (!usernames.length) return;

  const client = await getFullClient();
  const { NewMessage } = await import("telegram/events/NewMessage.js");

  client.addEventHandler(async (event) => {
    const msg = event.message;
    if (!msg || msg.out) return;
    const text = msg.message || "";
    if (text.length < 40) return;
    const chat = await event.getChat();
    const username = (chat as { username?: string }).username || "";
    if (!username || !usernames.includes(username)) return;
    const key = messageKey(username, msg.id);
    if (seen.has(key)) return;
    seen.add(key);
    const url = `https://t.me/${username}/${msg.id}`;
    try {
      await postToBackend({
        message_id: msg.id,
        channel: username,
        text,
        url,
        contact_hint: extractContactHint(text),
      });
      console.log(`[orderhunter] realtime ${username}/${msg.id}`);
    } catch (e) {
      console.error("[orderhunter] realtime ingest failed", e);
    }
  }, new NewMessage({ incoming: true, chats: usernames }));

  console.log(`[orderhunter] realtime listener on ${usernames.join(", ")}`);
}

export async function runMonitor(): Promise<void> {
  await startRealtimeListener();
  const interval = ENV.POLL_INTERVAL_SECONDS * 1000;
  setInterval(() => {
    pollChannelsOnce().catch((e) => console.error("[orderhunter] poll error", e));
  }, interval);
  await pollChannelsOnce();
}
