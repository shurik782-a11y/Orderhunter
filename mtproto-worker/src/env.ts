import "dotenv/config";

function req(name: string): string {
  const v = process.env[name]?.trim();
  if (!v) throw new Error(`Missing env: ${name}`);
  return v;
}

export const ENV = {
  TELEGRAM_API_ID: Number(req("TELEGRAM_API_ID")),
  TELEGRAM_API_HASH: req("TELEGRAM_API_HASH"),
  TELEGRAM_USER_SESSION: req("TELEGRAM_USER_SESSION"),
  TELEGRAM_PROXY_URL: process.env.TELEGRAM_PROXY_URL?.trim() || "",
  ORDERHUNTER_BACKEND_URL: (process.env.ORDERHUNTER_BACKEND_URL || "http://localhost:8000").replace(/\/$/, ""),
  INTERNAL_API_SECRET: req("INTERNAL_API_SECRET"),
  CHANNELS_CONFIG: process.env.CHANNELS_CONFIG || "../config/telegram-channels.yaml",
  POLL_INTERVAL_SECONDS: Number(process.env.POLL_INTERVAL_SECONDS || "90"),
};
