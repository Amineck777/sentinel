# 05 主人格をチャットにつなぐ

## 一言で

Ollama の `eva` モデル(人格は Modelfile の SYSTEM)を、SENTINEL のチャット画面で選べるようにした。
SENTINEL は**system を送らない**・**思考を切る**・**返答をモデル名つきで SQLite に残す**、の3つが要点。

## 背景

- エヴァの人格は `persona_private/ollama/Modelfile` にあり、`ollama run eva --think=false` で仕様どおりに話せていた
- ところが SENTINEL はこれまで、毎ターン「あなたはSENTINEL…」という system を送っていた。
  Ollama は**リクエストに system があると、Modelfile の SYSTEM より優先する**ので、そのままではエヴァの人格が消える
- gemma4 は思考モデル。思考させると返答が数十秒遅れる。チャットでは `--think=false` と同じことを API でもしたい
- 毎日の会話は、後で学習データの元になる。そのとき「どのモデルが言ったか」が分からないと、
  モデルを替えたあとに古い返答と新しい返答が混ざる

## しくみ

```
画面で「エヴァ」を選ぶ
  → registry がアクティブPackを eva に(kv に保存。次回起動でも eva)
発言を送る
  → ChatService._generate_turn
       Pack が system_prompt: model なら system を付けない(履歴だけ)
       model=eva を LLM に渡す
  → OpenAICompatClient が POST /v1/chat/completions
       {"model": "eva", "messages": [...], "reasoning_effort": "none"}
       ↑ Ollama はこれを think=false として扱う
  → 返答を messages に保存(model 列 = "eva")
```

- Pack の読み込み: `core/sentinel_core/character/pack.py`(`llm.model` / `llm.system_prompt`)
- system を送るかの分岐: `core/sentinel_core/agent/service.py` の `_generate_turn`
- 思考オフと、受け付けないサーバーへのやり直し: `core/sentinel_core/llm/openai_compat.py`
- DB の版3(`messages.model` 列): `core/sentinel_core/memory/store.py` の `_V3`
- 私的 Pack を入れる道具: `scripts/install_pack.py`

### なぜ人格を Pack の .md ではなく Modelfile に置いたままにしたか

人格の正は人格仕様書で、そこから Modelfile を作って `smoke_test` で確かめてある。
同じ文を Pack の `persona.md` にも写すと、片方だけ直して食い違う。
「どのモデルを使うか」だけを Pack に書き、人格の本文は1か所(Modelfile)に保つ。
代わりに SENTINEL の土台の方針(正確さ優先・破壊的操作は確認)は、このキャラでは送られない。
ツール実行(Phase 2)を入れるときに、Modelfile 側へ足すか、system を合成する方式へ戻すかを決める。

### 私的 Pack をリポジトリに入れない

エヴァの Pack は `C:\Myself_Project\AI_Assistant\persona_private\sentinel_pack\eva\` にある(リポジトリの外)。
`install_pack.py` が、コアが読む `{APP_DATA}/sentinel/characters/eva/` へコピーする。
Windows では `%LOCALAPPDATA%\sentinel\sentinel\characters\` になる。

## やってみる

1. Ollama が動いていて `eva` があるか: `ollama list`
2. Pack を入れる(リポジトリ直下で):
   `core\.venv\Scripts\python.exe scripts\install_pack.py C:\Myself_Project\AI_Assistant\persona_private\sentinel_pack\eva`
3. コアと画面を起動し、右上の character で「エヴァ」を選んで話す
4. 歯車の「接続」でモデルが `eva` になっているか見る
5. 会話が残ったか(SQLite):
   `core\.venv\Scripts\python.exe -c "import sqlite3,os;c=sqlite3.connect(os.path.expandvars(r'%LOCALAPPDATA%\sentinel\sentinel\data\sentinel.db'));print(c.execute('select role,model,content from messages order by rowid desc limit 4').fetchall())"`

## ハマりどころ

- **system を1行でも送ると Modelfile の人格が消える**。「少しだけ足す」はできない(足すなら全文を送る方式になる)
- **`reasoning_effort: "none"` を知らない古い Ollama は 400 を返す**。クライアントは1回だけ外してやり直し、以後は送らない。
  その場合は思考が残って遅いので、Ollama を更新する
- **Pack のバックアップを characters/ の中に置かない**。同じ id の Pack が2つ読まれ、古い方が勝つことがある
  (`install_pack.py` は `characters_backup/` へ退避する)
- キャラを切り替えると新しい会話(セッション)になる。前のキャラの履歴は混ぜない

## 確認問題

1. エヴァを選んだとき、SENTINEL が system を送らないのはなぜか
2. `messages.model` 列が無いと、後で学習データを作るときに何が困るか
3. 思考オフの指定を受け付けないサーバーで、クライアントはどう振る舞うか
4. エヴァの Pack をリポジトリの外に置き、コピーで入れるのはなぜか
