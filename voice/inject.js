// Claude Code cross-session messaging 소켓에 자기 세션으로 postback.
// 훅/Bash 실행 컨텍스트에서 Claude Code가 넘겨주는 환경변수를 사용한다.
// 참고: docs/decisions.md 2026-09-25 "핵심 결정" 항목 (미검증, 최우선 후보)
"use strict";

const net = require("net");

const PIPE_PATH = process.env.CLAUDE_CODE_MESSAGING_SOCKET;
const TOKEN = process.env.CLAUDE_CODE_MESSAGING_TOKEN;

function injectMessage(text) {
  return new Promise((resolve, reject) => {
    if (!PIPE_PATH) {
      return reject(new Error("CLAUDE_CODE_MESSAGING_SOCKET 환경변수가 없습니다"));
    }
    if (!TOKEN) {
      return reject(new Error("CLAUDE_CODE_MESSAGING_TOKEN 환경변수가 없습니다"));
    }

    const socket = net.createConnection(PIPE_PATH);
    let settled = false;

    const finish = (err) => {
      if (settled) return;
      settled = true;
      socket.end();
      if (err) reject(err);
      else resolve();
    };

    socket.on("connect", () => {
      // 공식 예제(claude.exe 바이너리 debug 문자열)와 동일하게 한 번의 write로 합쳐 보낸다.
      // 두 번 나눠 쓰면 "완전한 한 줄"이 아닌 채로 도착해 조용히 drop될 수 있음(실측 확인).
      const payload =
        JSON.stringify({ type: "auth", token: TOKEN }) +
        "\n" +
        JSON.stringify({
          type: "user",
          message: { role: "user", content: text },
        }) +
        "\n";
      socket.write(payload);
      finish(null);
    });

    socket.on("error", (err) => finish(err));
    socket.setTimeout(5000, () => finish(new Error("소켓 연결 타임아웃")));
  });
}

if (require.main === module) {
  const text = process.argv.slice(2).join(" ");
  if (!text) {
    console.error("사용법: node inject.js <전송할 텍스트>");
    process.exit(1);
  }
  injectMessage(text)
    .then(() => console.log("전송 완료"))
    .catch((err) => {
      console.error("전송 실패:", err.message);
      process.exit(1);
    });
}

module.exports = { injectMessage };
