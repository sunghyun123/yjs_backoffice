import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import {
  MAX_DAYS_AGO,
  RelayError,
  TOOL_DESCRIPTION,
  fetchDay,
  formatDay,
  parseServerUrl,
} from "./relay.js";

const server = new McpServer({ name: "yj-mail", version: "0.1.0" });

server.registerTool(
  "get_mail",
  {
    title: "하루치 메일 가져오기",
    description: TOOL_DESCRIPTION,
    inputSchema: {
      days_ago: z.number().int().min(0).max(MAX_DAYS_AGO).default(1)
        .describe("오늘로부터 며칠 전인지. 0=오늘, 1=어제"),
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ days_ago }) => {
    try {
      // 설정은 호출마다 읽는다. 주소를 잘못 넣어도 서버 기동은 되고, 실패 이유가 대화에 그대로 보이게.
      const base = parseServerUrl(process.env.YJ_SERVER_URL);
      const result = await fetchDay(base, days_ago);
      return { content: [{ type: "text", text: formatDay(result) }] };
    } catch (error) {
      const text = error instanceof RelayError ? error.message : "메일을 가져오지 못했습니다.";
      // stdout은 MCP 통신 전용이라 진단은 stderr로만 남긴다(메일 내용은 남기지 않는다).
      console.error(`[yj-mail] get_mail 실패: ${error?.name ?? "Error"}`);
      return { isError: true, content: [{ type: "text", text }] };
    }
  },
);

await server.connect(new StdioServerTransport());
