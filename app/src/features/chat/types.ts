/** system は画面だけのお知らせ(キャラ切替など)。会話の発言ではない */
export type Msg = { role: "user" | "assistant" | "system"; text: string; pending?: boolean };

export type Character = { id: string; display_name: string; valid: boolean };

export type Health = {
  llm_reachable: boolean;
  active_character: string | null;
  /** 今のキャラで使うモデル名(キャラが指定しなければ config.yaml の llm.chat_model) */
  chat_model?: string;
  version: string;
};
