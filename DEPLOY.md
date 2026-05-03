# manacam.keto-web.com 公開手順

`keto-web.com` は現在 Xdomain のネームサーバーで管理されています。

```text
ns1.xdomain.ne.jp
ns2.xdomain.ne.jp
ns3.xdomain.ne.jp
```

そのため、`manacam.keto-web.com` を固定URLにするには、アプリを外部ホスティングへ置き、Xdomain側でサブドメインのDNSレコードを追加します。

## 推奨構成

```text
manacam.keto-web.com
  -> CNAME
  -> ホスティング先のCNAMEターゲット
  -> FastAPIアプリ
```

GitHub Pages は静的サイト専用なので、このFastAPIアプリ本体は置けません。

## 1. アプリをデプロイする

Render / Railway / Fly.io / VPS など、Python FastAPIを動かせる場所にデプロイします。

必要な環境変数:

```text
GEMINI_API_KEY=Google AI StudioのAPIキー
GEMINI_MODEL=gemini-3.1-flash-lite-preview
```

起動コマンド:

```bash
uvicorn webapp:app --host 0.0.0.0 --port $PORT
```

Renderを使う場合は、このフォルダの `render.yaml` を使えます。

## 2. ホスティング側でカスタムドメインを追加

ホスティング側の管理画面で、カスタムドメインに以下を追加します。

```text
manacam.keto-web.com
```

追加後、CNAMEターゲットが表示されます。

例:

```text
manacam-school.onrender.com
```

## 3. XdomainでDNSレコードを追加

XdomainのDNS設定で、以下のレコードを追加します。

```text
ホスト名: manacam
タイプ: CNAME
値: ホスティング側に表示されたCNAMEターゲット
TTL: デフォルト
```

`keto-web.com` 本体のAレコードやCNAMEは触らないでください。

## 4. 反映確認

DNS反映後、以下で確認します。

```powershell
Resolve-DnsName manacam.keto-web.com -Type CNAME
```

ブラウザで開きます。

```text
https://manacam.keto-web.com
```

## 注意

- 「最近作ったプリント」はブラウザのlocalStorage保存なので、他の端末には表示されません。
- PDFリンクを直接共有した場合、そのリンクを知っている人は開けます。
- 無料ホスティングでは、再起動や再デプロイで `output/` 内のPDFが消える場合があります。重要なPDFは生成直後にダウンロードしてください。
