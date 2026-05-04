# ManaCam for ココリュウスクール

ココリュウスクール（兵庫県伊丹市・小学生向け算数教室・りうさん運営）専用の教材プリント生成アプリ。

## 目的

先生が **学年 → 単元 → 難易度 → 問題タイプ** を選ぶだけで、小学生向け算数の演習プリントPDFを作る。

- 生徒配布用: 解答スペース付きのA4プリント
- 先生用: 答え、ヒント、必要に応じて途中式・解説
- 単元は1つだけ選ぶシンプル設計
- 生成後に問題文・答えを画面上で修正し、PDFを再作成できる
- 整数の計算式は、チェックなしでも数字入りの筆算マスに自動配置できる
- 分数・小数・図形問題などには、必要に応じて空の計算マスを追加できる
- 最近作ったPDFの一覧は、その端末のブラウザ内だけに保存する

## 現在の仕様

| 項目 | 内容 |
|------|------|
| 対象 | 小1〜小6 |
| 科目 | 算数 |
| 入力 | 学年・単元・問題数・難易度・問題タイプ |
| 出力 | A4 PDF |
| LLM | Gemini API |
| Web | FastAPI + HTML/CSS/Vanilla JS |
| PDF | ReportLab |

## セットアップ

`.env.example` を参考に `.env` を作成し、Gemini APIキーを設定する。

```env
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-3.1-flash-lite-preview
```

依存関係を入れる。

```bash
pip install -r requirements.txt
```

## 起動

```bash
python -m uvicorn webapp:app --port 8005 --reload
```

ブラウザで開く。

```text
http://localhost:8005
```

外部に一時公開する場合。

```bash
cloudflared tunnel --url http://localhost:8005
```

Windowsでは `start.bat` でWebappとCloudflaredをまとめて起動できる。

## 動作確認

PDF生成だけを確認する。

```bash
python make_pdf.py
```

旧OCRパイプラインを試す場合。

```bash
python test_full.py test_images/IMG_7464.jpg --grade 小5 --n 8
```

## ファイル構成

| ファイル | 役割 |
|---------|------|
| `webapp.py` | 単元選択型Webアプリ |
| `curriculum.json` | 小学校算数の単元一覧 |
| `test_summary.py` | Geminiで問題生成 |
| `make_pdf.py` | A4 PDF生成 |
| `history.jsonl` | 生成履歴 |
| `test_ocr.py` | Google Vision OCR検証用 |
| `test_full.py` | 旧画像OCRパイプライン |
| `output/` | 生成PDF |
| `uploads/` | 画像アップロード検証時の保存先 |

## 関連資料

- 商談ヒアリングシート: `C:\Claude Code Pro\output\plans\2026-05-02_kokoryuschool_hearing.md`
- ココリュウスクール: https://www.kokoryuschool.shop/
