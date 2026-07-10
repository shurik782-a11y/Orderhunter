import "dotenv/config";

function req(name: string): string {
  const v = process.env[name]?.trim();
  if (!v) {
    throw new Error(
      `Missing Railway Variable: ${name}\n` +
        `Set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, INTERNAL_API_SECRET on the mtproto service.`,
    );
  }
  return v;
}

function reqApiId(): number {
  const raw = req("TELEGRAM_API_ID");
  const id = Number(raw);
  if (!Number.isFinite(id) || id <= 0) {
    throw new Error(
      `TELEGRAM_API_ID must be a positive number from https://my.telegram.org (got: ${JSON.stringify(raw)})`,
    );
  }
  return id;
}

export const ENV = {
  TELEGRAM_API_ID: reqApiId(),
  TELEGRAM_API_HASH: req("TELEGRAM_API_HASH"),
  TELEGRAM_USER_SESSION: req("TELEGRAM_USER_SESSION"),
  TELEGRAM_PROXY_URL: process.env.TELEGRAM_PROXY_URL?.trim() || "",
  ORDERHUNTER_BACKEND_URL: (
    process.env.ORDERHUNTER_BACKEND_URL || "http://localhost:8000"
  ).replace(/\/$/, ""),
  INTERNAL_API_SECRET: req("INTERNAL_API_SECRET"),
  CHANNELS_CONFIG: process.env.CHANNELS_CONFIG || "../config/telegram-channels.yaml",
  POLL_INTERVAL_SECONDS: Number(process.env.POLL_INTERVAL_SECONDS || "90"),
};

console.log("[orderhunter] env ok", {
  apiId: ENV.TELEGRAM_API_ID,
  hashLen: ENV.TELEGRAM_API_HASH.length,
  sessionLen: ENV.TELEGRAM_USER_SESSION.length,
  backend: ENV.ORDERHUNTER_BACKEND_URL,
});
