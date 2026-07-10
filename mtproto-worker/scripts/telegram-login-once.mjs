/**
 * Вход в личный Telegram → TELEGRAM_USER_SESSION
 *   npm run telegram:login
 */
import { config } from "dotenv";
import fs from "fs";
import path from "path";
import readline from "readline";
import { fileURLToPath } from "url";
import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions/index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
config({ path: path.join(repoRoot, ".env") });

const apiId = Number(process.env.TELEGRAM_API_ID);
const apiHash = String(process.env.TELEGRAM_API_HASH ?? "").trim();

function createPrompter() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return {
    ask(question) {
      return new Promise((resolve) => {
        rl.question(question, (answer) => resolve(String(answer ?? "").trim()));
      });
    },
    close() {
      rl.close();
    },
  };
}

function normalizePhone(raw) {
  let s = String(raw ?? "").replace(/[\s\-()]/g, "");
  if (!s) return "";
  if (s.startsWith("00")) s = "+" + s.slice(2);
  if (!s.startsWith("+")) {
    if (s.startsWith("8") && s.length === 11) s = "+7" + s.slice(1);
    else if (s.startsWith("7") && s.length === 11) s = "+" + s;
    else s = "+" + s;
  }
  return s;
}

function normalizeCode(raw) {
  return String(raw ?? "").replace(/\D/g, "");
}

if (!apiId || !apiHash) {
  console.error("Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env");
  process.exit(1);
}

const prompter = createPrompter();
const client = new TelegramClient(new StringSession(""), apiId, apiHash, {
  connectionRetries: 10,
  useWSS: true,
});
client.setLogLevel("error");

try {
  await client.start({
    phoneNumber: async () => {
      for (;;) {
        const phone = normalizePhone(await prompter.ask("Номер (+79...): "));
        if (/^\+\d{10,15}$/.test(phone)) return phone;
        console.error("  Пример: +79337518613");
      }
    },
    phoneCode: async () => {
      for (;;) {
        const code = normalizeCode(await prompter.ask("Код (5 цифр): "));
        if (/^\d{5}$/.test(code)) return code;
      }
    },
    password: async () => await prompter.ask("2FA (или Enter): "),
    onError: async (err) => {
      console.error(err?.errorMessage ?? err?.message ?? err);
      return false;
    },
  });

  const session = client.session.save();
  await client.disconnect();
  prompter.close();

  const outFile = path.join(repoRoot, ".telegram-user-session.local.txt");
  fs.writeFileSync(outFile, session + "\n", { encoding: "utf8", mode: 0o600 });
  console.log(`\nTELEGRAM_USER_SESSION:\n${session}\n\nСохранено: ${outFile}\n`);
  console.log(
    "Важно: одну session-строку нельзя использовать в двух процессах (AUTH_KEY_DUPLICATED).\n" +
      "Нужны Railway + локально — запустите login ещё раз и получите ВТОРУЮ строку для второго места.\n",
  );
} catch (e) {
  prompter.close();
  console.error(e);
  process.exit(1);
}
