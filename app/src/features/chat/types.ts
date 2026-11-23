export type Msg = { role: "user" | "assistant"; text: string; pending?: boolean };

export type Character = { id: string; display_name: string; valid: boolean };

export type Health = {
  llm_reachable: boolean;
  active_character: string | null;
  /** 今のキャラで使うモデル名(キャラが指定しなければ config.yaml の llm.chat_model) */
  chat_model?: string;
  version: string;
};
