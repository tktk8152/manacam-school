"""
ManaCam for KOKORYUSCHOOL - Webアプリ（単元選択型 v2）
学年→単元→難易度→問題数 を選ぶだけで、学習指導要領ベースの演習プリントを生成

起動:
  cd C:\\manacam-school
  python -m uvicorn webapp:app --port 8005 --reload

アクセス:
  ローカル: http://localhost:8005
  外部公開: cloudflared tunnel --url http://localhost:8005
"""
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

sys.path.insert(0, str(Path(__file__).parent))
from test_summary import generate_from_unit, generate_from_units
from make_pdf import make_pdf


BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CURRICULUM_PATH = BASE_DIR / "curriculum.json"
HISTORY_PATH = BASE_DIR / "history.jsonl"

ALLOWED_GRADES = {"小1", "小2", "小3", "小4", "小5", "小6"}
ALLOWED_DIFFICULTIES = {"基礎", "標準", "応用", "ハイレベル"}
ALLOWED_ANSWER_MODES = {"none", "answer_only", "with_steps", "with_explanation"}
ALLOWED_PRINT_STYLES = {"standard", "spacious", "compact"}
ALLOWED_PROBLEM_TYPES = {
    "おまかせ",
    "計算問題",
    "文章題",
    "穴埋め",
    "選択問題",
    "まとめ問題",
    "ミスしやすい問題",
}


def safe_filename(s: str, max_len: int = 50) -> str:
    """ファイル名に使えない文字を除去 + 長さ制限"""
    bad = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\n', '\r', '\t']
    out = (s or "").strip()
    for b in bad:
        out = out.replace(b, "_")
    out = out.strip().strip(".")
    if len(out) > max_len:
        out = out[:max_len]
    return out or "untitled"


def save_history(record: dict) -> None:
    """生成履歴を1行追記する"""
    try:
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_history(limit: int = 50) -> list:
    """履歴を新しい順で返す"""
    if not HISTORY_PATH.exists():
        return []
    items = []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    items.reverse()  # 新しい順
    return items[:limit]


def format_history_item(item: dict) -> dict:
    """画面表示用に履歴へPDF URLと存在フラグを付ける"""
    filename = str(item.get("pdf_filename", ""))
    safe = filename.replace("..", "").replace("/", "").replace("\\", "")
    exists = bool(safe and (OUTPUT_DIR / safe).exists())
    return {
        **item,
        "pdf_filename": safe,
        "pdf_url": f"/pdf/{quote(safe)}" if exists else "",
        "exists": exists,
    }


def load_curriculum():
    """毎リクエスト curriculum.json を読み直す（更新を即時反映）"""
    with open(CURRICULUM_PATH, encoding="utf-8") as f:
        cur = json.load(f)
    index = {}
    for grade, units in cur["grades"].items():
        for u in units:
            index[u["id"]] = {**u, "grade": grade}
    return cur, index


app = FastAPI(title="ココリュウスクール 教材アシスタント")


def _build_curriculum_js(curriculum) -> str:
    """JS埋め込み用の単元データ（印刷対応のもののみ）"""
    js_data = {}
    for grade, units in curriculum["grades"].items():
        js_data[grade] = [
            {"id": u["id"], "name": u["name"], "category": u["category"]}
            for u in units
            if u.get("supports_print")
        ]
    return json.dumps(js_data, ensure_ascii=False)


INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ココリュウスクール 教材アシスタント</title>
<script>
(function(){
  try {
    var saved = localStorage.getItem('manacam-theme');
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = saved || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  } catch(e){}
})();
</script>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Meiryo", sans-serif;
    margin: 0; padding: 0;
    background: #faf7f2; color: #2a2a2a; line-height: 1.6;
  }
  .container { max-width: 760px; margin: 0 auto; padding: 24px 20px 60px; }
  header {
    text-align: center; padding: 32px 0 24px;
    border-bottom: 1px solid #e5dfd4; margin-bottom: 32px;
  }
  header .logo { font-size: 14px; color: #8b7355; letter-spacing: 0.1em; margin-bottom: 6px; }
  header h1 { font-size: 22px; margin: 0; font-weight: 600; }
  .card {
    background: #fff; border-radius: 12px; padding: 24px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 16px;
  }
  label {
    display: block; font-size: 13px; font-weight: 600;
    margin-bottom: 8px; color: #555;
  }
  select {
    width: 100%; padding: 12px;
    border: 1px solid #d8d0c0; border-radius: 8px;
    font-size: 15px; background: #fff;
    margin-bottom: 16px; font-family: inherit;
  }
  select:disabled { background: #f5f1e8; color: #aaa; }
  .row { display: flex; gap: 12px; }
  .row > div { flex: 1; min-width: 0; }
  @media (max-width: 600px) {
    .row { flex-wrap: wrap; }
    .row > div { flex-basis: 100%; }
  }
  button {
    width: 100%; padding: 16px;
    background: #6b8e4e; color: #fff;
    border: none; border-radius: 8px;
    font-size: 16px; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  button:hover { background: #587842; }
  button:disabled { background: #b8bfa8; cursor: not-allowed; }
  .status { text-align: center; padding: 16px; color: #666; font-size: 14px; }
  .result {
    background: #f0f5ea; border: 1px solid #c8d8b8;
    border-radius: 8px; padding: 20px; margin-top: 16px;
  }
  .result h3 { margin: 0 0 12px; font-size: 16px; color: #4a6b35; }
  .result .summary { font-size: 13px; color: #555; margin-bottom: 12px; line-height: 1.6; }
  .qitem {
    margin: 8px 0; padding: 10px;
    background: #fff; border-radius: 6px; font-size: 14px;
  }
  .qitem .qtext { margin-bottom: 4px; }
  .qitem .ans { color: #888; font-size: 13px; }
  .download-btn {
    display: block; text-align: center;
    background: #4a6b35; color: #fff;
    padding: 14px; border-radius: 8px;
    text-decoration: none; font-weight: 600; margin-top: 12px;
  }
  .error {
    background: #fbecec; border: 1px solid #e6b8b8; color: #8a3a3a;
    border-radius: 8px; padding: 16px; margin-top: 16px; font-size: 14px;
  }
  footer { text-align: center; color: #aaa; font-size: 12px; margin-top: 40px; }
  .note {
    font-size: 12px; color: #888; line-height: 1.5;
    background: #f5f1e8; border-radius: 6px;
    padding: 10px 12px; margin-top: -8px; margin-bottom: 16px;
  }
  .spinner {
    display: inline-block; width: 18px; height: 18px;
    border: 2px solid #fff; border-top-color: transparent;
    border-radius: 50%; animation: spin 0.8s linear infinite;
    margin-right: 8px; vertical-align: middle;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  [data-theme="dark"] body { background: #141414; color: #e2e2e2; }
  [data-theme="dark"] header { border-bottom-color: #2c2c2c; }
  [data-theme="dark"] header .logo { color: #b8a585; }
  [data-theme="dark"] header h1 { color: #f0f0f0; }
  [data-theme="dark"] .card { background: #1f1f1f; box-shadow: 0 1px 3px rgba(0,0,0,0.4); }
  [data-theme="dark"] label { color: #aaa; }
  [data-theme="dark"] select { background: #2a2a2a; color: #e2e2e2; border-color: #3a3a3a; }
  [data-theme="dark"] select:disabled { background: #1a1a1a; color: #666; }
  [data-theme="dark"] .note { background: #2a2a2a; color: #888; }
  [data-theme="dark"] .status { color: #bbb; }
  [data-theme="dark"] .result { background: #1c2a1a; border-color: #2f4a28; }
  [data-theme="dark"] .result h3 { color: #98c478; }
  [data-theme="dark"] .result .summary { color: #b0b0b0; }
  [data-theme="dark"] .qitem { background: #2a2a2a; color: #e2e2e2; }
  [data-theme="dark"] .qitem .ans { color: #999; }
  [data-theme="dark"] .download-btn { background: #5a8044; }
  [data-theme="dark"] .download-btn:hover { background: #4a6b35; }
  [data-theme="dark"] .error { background: #3a1f1f; border-color: #5a2a2a; color: #f0a8a8; }
  [data-theme="dark"] footer { color: #555; }
  [data-theme="dark"] button { background: #5a8044; }
  [data-theme="dark"] button:hover { background: #4a6b35; }
  [data-theme="dark"] button:disabled { background: #3a3a3a; color: #777; }

  .unit-picker { display: flex; gap: 8px; margin-bottom: 8px; }
  .unit-picker select { flex: 1; margin-bottom: 0; }
  .unit-picker button {
    width: auto; padding: 0 16px; margin: 0;
    background: #8b7355; font-size: 14px; flex-shrink: 0;
  }
  .unit-picker button:hover { background: #6e5a40; }
  .unit-picker button:disabled { background: #ccc; cursor: not-allowed; }
  .unit-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; min-height: 4px; }
  .unit-chip {
    background: #e8f0e0; color: #4a6b35;
    padding: 5px 12px; border-radius: 16px;
    font-size: 13px; display: inline-flex; align-items: center; gap: 6px;
  }
  .unit-chip .remove {
    cursor: pointer; color: #888;
    font-size: 16px; line-height: 1;
    padding: 0 2px; user-select: none;
  }
  .unit-chip .remove:hover { color: #555; }
  [data-theme="dark"] .unit-chip { background: #2a3a25; color: #b8d8a0; }
  [data-theme="dark"] .unit-chip .remove { color: #777; }
  [data-theme="dark"] .unit-chip .remove:hover { color: #aaa; }

  .progress-bar {
    width: 100%; height: 3px;
    background: #e5dfd4; border-radius: 2px;
    overflow: hidden; margin-top: 8px;
  }
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, transparent, #6b8e4e 50%, transparent);
    background-size: 200% 100%;
    animation: progress-slide 1.4s ease-in-out infinite;
  }
  @keyframes progress-slide {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  [data-theme="dark"] .progress-bar { background: #2a2a2a; }
  [data-theme="dark"] .progress-fill {
    background: linear-gradient(90deg, transparent, #5a8044 50%, transparent);
    background-size: 200% 100%;
  }
  .qitem .qtext-input, .qitem .qans-input, .qitem .choice-label-input, .qitem .choice-text-input {
    width: 100%; padding: 4px 6px; margin-top: 2px;
    border: 1px solid transparent; background: transparent;
    color: inherit; font-size: 14px; font-family: inherit;
    border-radius: 4px;
  }
  .qitem .qtext-input:hover, .qitem .qans-input:hover,
  .qitem .choice-label-input:hover, .qitem .choice-text-input:hover {
    border-color: #d8d0c0;
  }
  .qitem .qtext-input:focus, .qitem .qans-input:focus,
  .qitem .choice-label-input:focus, .qitem .choice-text-input:focus {
    border-color: #6b8e4e; outline: none; background: #f8faf3;
  }
  [data-theme="dark"] .qitem .qtext-input:hover,
  [data-theme="dark"] .qitem .qans-input:hover,
  [data-theme="dark"] .qitem .choice-label-input:hover,
  [data-theme="dark"] .qitem .choice-text-input:hover { border-color: #444; }
  [data-theme="dark"] .qitem .qtext-input:focus,
  [data-theme="dark"] .qitem .qans-input:focus,
  [data-theme="dark"] .qitem .choice-label-input:focus,
  [data-theme="dark"] .qitem .choice-text-input:focus {
    background: #1a1a1a; border-color: #5a8044;
  }
  .qitem .ans-row { display: flex; align-items: baseline; gap: 6px; color: #888; font-size: 13px; }
  .qitem .ans-row .label { white-space: nowrap; }
  .qitem .choice-list {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 6px; margin: 8px 0 6px;
  }
  .qitem .choice-edit-row {
    display: flex; align-items: center; gap: 4px;
    border: 1px solid #d8d0c0; background: #fbfcf8;
    border-radius: 6px; padding: 3px 5px;
  }
  .qitem .choice-label-input {
    width: 34px; flex: 0 0 34px; text-align: center; font-weight: 600;
    background: #fff; border-color: #d8d0c0;
  }
  .qitem .choice-text-input { flex: 1; min-width: 0; }
  [data-theme="dark"] .qitem .choice-edit-row {
    background: #242424; border-color: #444;
  }
  [data-theme="dark"] .qitem .choice-label-input {
    background: #1a1a1a; border-color: #444;
  }
  .apply-edit-btn {
    width: 100%; margin-top: 8px;
    background: #506b5a; color: #fff;
    border: none; border-radius: 8px;
    padding: 12px; font-size: 14px; font-weight: 600;
    cursor: pointer;
  }
  .apply-edit-btn:hover { background: #3e5546; }
  [data-theme="dark"] .apply-edit-btn { background: #4a6b5a; }
  [data-theme="dark"] .apply-edit-btn:hover { background: #3a5b4a; }

  .history-card h2 {
    font-size: 15px; margin: 0 0 12px;
    color: #4a4a4a; font-weight: 600;
  }
  .history-list { display: flex; flex-direction: column; gap: 8px; }
  .history-item {
    display: flex; justify-content: space-between; align-items: center;
    gap: 10px; padding: 10px 0; border-top: 1px solid #eee6d8;
    font-size: 13px;
  }
  .history-item:first-child { border-top: 0; padding-top: 0; }
  .history-main { min-width: 0; }
  .history-title {
    color: #333; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; max-width: 520px;
  }
  .history-meta { color: #8a8172; font-size: 12px; margin-top: 2px; }
  .history-link {
    flex-shrink: 0; color: #4a6b35; text-decoration: none;
    font-weight: 600;
  }
  .history-empty { color: #888; font-size: 13px; }
  [data-theme="dark"] .history-card h2 { color: #ddd; }
  [data-theme="dark"] .history-item { border-top-color: #2d2d2d; }
  [data-theme="dark"] .history-title { color: #e2e2e2; }
  [data-theme="dark"] .history-meta { color: #888; }
  [data-theme="dark"] .history-link { color: #98c478; }


  .checkbox-label {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: #555; margin-bottom: 16px;
    cursor: pointer; user-select: none;
  }
  .checkbox-label input[type="checkbox"] {
    width: auto; margin: 0;
  }
  [data-theme="dark"] .checkbox-label { color: #aaa; }
  .retry-btn, .regenerate-btn {
    width: 100%; margin-top: 12px;
    background: #8b7355; color: #fff;
    border: none; border-radius: 8px;
    padding: 12px; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  .retry-btn:hover, .regenerate-btn:hover { background: #6e5a40; }
  .retry-btn { background: #888; }
  .retry-btn:hover { background: #666; }
  [data-theme="dark"] .retry-btn { background: #555; }
  [data-theme="dark"] .retry-btn:hover { background: #444; }
  [data-theme="dark"] .regenerate-btn { background: #6b5b4a; }
  [data-theme="dark"] .regenerate-btn:hover { background: #5a4a3a; }

  .theme-toggle {
    position: fixed; bottom: 16px; right: 16px;
    width: 38px; height: 38px; border-radius: 50%;
    background: #fff; border: 1px solid #d8d0c0;
    cursor: pointer; font-size: 18px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
    z-index: 100; padding: 0;
    display: flex; align-items: center; justify-content: center;
    transition: transform 0.15s;
  }
  .theme-toggle:hover { transform: scale(1.08); }
  [data-theme="dark"] .theme-toggle { background: #2a2a2a; border-color: #3a3a3a; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">KOKORYUSCHOOL</div>
    <h1>教材アシスタント</h1>
  </header>

  <form id="form" class="card">
    <label>学年</label>
    <select name="grade" id="grade">
      <option value="">選んでください</option>
      <option value="小1">小1</option>
      <option value="小2">小2</option>
      <option value="小3">小3</option>
      <option value="小4">小4</option>
      <option value="小5">小5</option>
      <option value="小6">小6</option>
    </select>

    <label>単元</label>
    <select id="unit_picker_select" disabled>
      <option value="">先に学年を選んでください</option>
    </select>
    <div class="note">学習指導要領に沿ったオリジナル問題を生成します。市販テキストは参照しません。</div>

    <div class="row row-3">
      <div>
        <label>問題数</label>
        <select name="num_questions" id="num_questions">
          <option value="4">4問</option>
          <option value="6">6問</option>
          <option value="8" selected>8問</option>
          <option value="10">10問</option>
        </select>
      </div>
      <div>
        <label>難易度</label>
        <select name="difficulty" id="difficulty">
          <option value="基礎">基礎</option>
          <option value="標準" selected>標準</option>
          <option value="応用">応用</option>
          <option value="ハイレベル">ハイレベル</option>
        </select>
      </div>
      <div>
        <label>問題タイプ</label>
        <select name="problem_type" id="problem_type">
          <option value="おまかせ" selected>おまかせ</option>
          <option value="計算問題">計算問題</option>
          <option value="文章題">文章題</option>
          <option value="穴埋め">穴埋め</option>
          <option value="選択問題">選択問題</option>
          <option value="まとめ問題">まとめ問題</option>
          <option value="ミスしやすい問題">ミス対策</option>
        </select>
      </div>
    </div>

    <label>解答ページ</label>
    <select name="answer_mode" id="answer_mode">
      <option value="none">解答ページなし</option>
      <option value="answer_only" selected>答えのみ</option>
      <option value="with_steps">答え＋途中式</option>
      <option value="with_explanation">答え＋詳しい解説</option>
    </select>

    <label class="checkbox-label">
      <input type="checkbox" id="include_score">
      点数欄を入れる（__ / 100点）
    </label>

    <label class="checkbox-label">
      <input type="checkbox" id="include_work_grid">
      筆算用のマス目を入れる（数字だけの式）
    </label>

    <button type="submit" id="submit-btn">プリントを作る</button>
  </form>

  <div id="status"></div>
  <div id="result"></div>

  <section class="card history-card">
    <h2>この端末で最近作ったプリント</h2>
    <div id="history-list" class="history-list">
      <div class="history-empty">読み込み中です...</div>
    </div>
  </section>

  <footer>ManaCam for ココリュウスクール</footer>
</div>

<button class="theme-toggle" id="theme-toggle" aria-label="テーマ切り替え" type="button">🌙</button>

<script>
const CURRICULUM = __CURRICULUM_JSON__;

const themeBtn = document.getElementById('theme-toggle');
function syncThemeBtn() {
  const t = document.documentElement.getAttribute('data-theme');
  themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
}
syncThemeBtn();
themeBtn.addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('manacam-theme', next); } catch(e){}
  syncThemeBtn();
});
const gradeSelect = document.getElementById('grade');
const unitPickerSelect = document.getElementById('unit_picker_select');
const submitBtn = document.getElementById('submit-btn');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');

gradeSelect.addEventListener('change', () => {
  const g = gradeSelect.value;
  unitPickerSelect.innerHTML = '';
  if (!g) {
    unitPickerSelect.disabled = true;
    unitPickerSelect.innerHTML = '<option value="">先に学年を選んでください</option>';
    return;
  }
  const units = CURRICULUM[g] || [];
  unitPickerSelect.disabled = false;
  unitPickerSelect.innerHTML = '<option value="">選んでください</option>' +
    units.map(u => `<option value="${u.id}">${u.name}</option>`).join('');
});


const LOADING_STAGES = [
  '問題を考えています…',
  '答えを組み立てています…',
  '答えの正しさを確認しています…',
  'ヒントを書いています…',
  'プリントを準備しています…',
  'もう少しで完成です…',
];
let stageInterval = null;
let currentResult = null;
let currentParams = null;
const LOCAL_HISTORY_KEY = 'manacam-recent-pdfs-v1';

function formatHistoryTime(s) {
  const raw = String(s || '');
  const m = raw.match(/^(\\d{8})_(\\d{6})$/);
  if (!m) return raw;
  return `${m[1].slice(4,6)}/${m[1].slice(6,8)} ${m[2].slice(0,2)}:${m[2].slice(2,4)}`;
}

function makeLocalTimestamp() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function getLocalHistory() {
  try {
    const raw = localStorage.getItem(LOCAL_HISTORY_KEY);
    const items = JSON.parse(raw || '[]');
    return Array.isArray(items) ? items : [];
  } catch (e) {
    return [];
  }
}

function saveLocalHistory(item) {
  const next = [
    item,
    ...getLocalHistory().filter(x => x.pdf_url !== item.pdf_url)
  ].slice(0, 8);
  try {
    localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(next));
  } catch (e) {}
  loadHistory();
}

function loadHistory() {
  const el = document.getElementById('history-list');
  if (!el) return;
  const items = getLocalHistory();
  if (!items.length) {
    el.innerHTML = '<div class="history-empty">この端末で作ったプリントはまだありません。</div>';
    return;
  }
  el.innerHTML = items.map(item => {
    const title = item.unit_name || item.unit || '算数プリント';
    const meta = [
      formatHistoryTime(item.timestamp),
      item.grade,
      item.difficulty,
      `${item.num_questions || '-'}問`,
      item.include_work_grid ? 'マス目' : ''
    ].filter(Boolean).join(' / ');
    const link = item.pdf_url
      ? `<a class="history-link" href="${item.pdf_url}" download>PDF</a>`
      : '<span class="history-meta">PDFなし</span>';
    return `
      <div class="history-item">
        <div class="history-main">
          <div class="history-title">${escapeHtml(title)}</div>
          <div class="history-meta">${escapeHtml(meta)}</div>
        </div>
        ${link}
      </div>
    `;
  }).join('');
}

function startLoading() {
  let idx = 0;
  statusEl.innerHTML = `
    <div class="status">
      <span class="spinner"></span>
      <span id="loading-text">${LOADING_STAGES[0]}</span>
    </div>
    <div class="progress-bar"><div class="progress-fill"></div></div>
  `;
  stageInterval = setInterval(() => {
    idx = Math.min(idx + 1, LOADING_STAGES.length - 1);
    const t = document.getElementById('loading-text');
    if (t) t.textContent = LOADING_STAGES[idx];
  }, 1800);
}
function stopLoading() {
  if (stageInterval) { clearInterval(stageInterval); stageInterval = null; }
  statusEl.innerHTML = '';
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderChoiceInputs(choices) {
  if (!Array.isArray(choices) || choices.length === 0) return '';
  const rows = choices.map((choice, j) => {
    const obj = choice && typeof choice === 'object' ? choice : {};
    const label = obj.label || obj.key || obj.id || '';
    const text = obj.text || obj.value || obj.choice || (typeof choice === 'string' ? choice : '');
    return `
      <div class="choice-edit-row" data-choice-index="${j}">
        <input type="text" class="choice-label-input" value="${escapeHtml(label)}" aria-label="選択肢ラベル">
        <input type="text" class="choice-text-input" value="${escapeHtml(text)}" aria-label="選択肢本文">
      </div>
    `;
  }).join('');
  return `<div class="choice-list">${rows}</div>`;
}

function renderResult(data) {
  const qList = (data.questions || []).map((qa, i) =>
    `<div class="qitem" data-index="${i}">
      <div><strong>Q${i+1}.</strong>
        <input type="text" class="qtext-input" value="${escapeHtml(qa.q)}">
      </div>
      ${renderChoiceInputs(qa.choices)}
      <div class="ans-row">
        <span class="label">答え:</span>
        <input type="text" class="qans-input" value="${escapeHtml(qa.a)}">
      </div>
    </div>`
  ).join('');

  resultEl.innerHTML = `
    <div class="result">
      <h3>✅ プリント完成</h3>
      <div class="summary">${escapeHtml(data.summary || '')}</div>
      ${qList}
      <div class="note" style="margin: 12px 0 0;">問題文や答えはクリックして直接編集できます。</div>
      <a id="download-link" href="${data.pdf_url}" class="download-btn" download>📄 PDFをダウンロード</a>
      <button class="apply-edit-btn" type="button" onclick="applyEdits()">📝 編集を反映してPDF再作成</button>
      <button class="regenerate-btn" type="button" onclick="generateProblems()">🔄 同じ条件で別の問題を作る</button>
    </div>
  `;
}

async function applyEdits() {
  if (!currentResult || !currentParams) return;
  const edited = JSON.parse(JSON.stringify(currentResult));
  document.querySelectorAll('.qitem').forEach((el, i) => {
    const q = el.querySelector('.qtext-input').value;
    const a = el.querySelector('.qans-input').value;
    if (edited.questions[i]) {
      edited.questions[i].q = q;
      edited.questions[i].a = a;
      const choiceRows = el.querySelectorAll('.choice-edit-row');
      if (choiceRows.length) {
        edited.questions[i].choices = Array.from(choiceRows).map(row => ({
          label: row.querySelector('.choice-label-input').value,
          text: row.querySelector('.choice-text-input').value
        })).filter(choice => choice.text.trim());
      }
    }
  });
  const btn = document.querySelector('.apply-edit-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'PDF再作成中…'; }

  try {
    const res = await fetch('/repdf', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ result: edited, ...currentParams })
    });
    const data = await res.json();
    if (data.error) {
      alert('再作成に失敗しました: ' + data.error);
    } else {
      currentResult = edited;
      const link = document.getElementById('download-link');
      if (link) link.href = data.pdf_url;
      if (btn) btn.textContent = '✅ 編集を反映しました（再ダウンロード可）';
      saveLocalHistory({
        timestamp: data.timestamp || makeLocalTimestamp(),
        unit_name: edited.unit || '算数プリント',
        grade: currentParams.grade,
        difficulty: currentParams.difficulty,
        num_questions: (edited.questions || []).length,
        pdf_url: data.pdf_url,
        include_work_grid: currentParams.include_work_grid === 'true'
      });
      setTimeout(() => { if (btn) btn.textContent = '📝 編集を反映してPDF再作成'; }, 2500);
    }
  } catch (err) {
    alert('通信エラー: ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function generateProblems() {
  const form = document.getElementById('form');
  const formData = new FormData(form);
  formData.set('include_score', document.getElementById('include_score').checked ? 'true' : 'false');
  formData.set('include_work_grid', document.getElementById('include_work_grid').checked ? 'true' : 'false');
  formData.set('print_style', 'standard');
  const unitId = unitPickerSelect.value;
  formData.set('unit_ids', unitId);

  if (!formData.get('grade') || !unitId) {
    resultEl.innerHTML = '<div class="error">⚠ 学年と単元を選んでください</div>';
    return;
  }

  resultEl.innerHTML = '';
  startLoading();
  submitBtn.disabled = true;
  submitBtn.textContent = '生成中…';

  try {
    const res = await fetch('/generate', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      stopLoading();
      resultEl.innerHTML = `
        <div class="error">⚠ ${escapeHtml(data.error || '生成に失敗しました')}</div>
        <button class="retry-btn" type="button" onclick="generateProblems()">もう一度試す</button>
      `;
      return;
    }

    stopLoading();
    currentResult = data;
    currentParams = {
      grade: formData.get('grade'),
      difficulty: formData.get('difficulty'),
      answer_mode: formData.get('answer_mode'),
      print_style: 'standard',
      include_score: document.getElementById('include_score').checked ? 'true' : 'false',
      include_work_grid: document.getElementById('include_work_grid').checked ? 'true' : 'false',
    };
    renderResult(data);
    saveLocalHistory({
      timestamp: data.timestamp || makeLocalTimestamp(),
      unit_name: data.unit || '算数プリント',
      grade: formData.get('grade'),
      difficulty: formData.get('difficulty'),
      num_questions: (data.questions || []).length,
      pdf_url: data.pdf_url,
      include_work_grid: document.getElementById('include_work_grid').checked
    });
  } catch (err) {
    stopLoading();
    resultEl.innerHTML = `
      <div class="error">⚠ エラー: ${escapeHtml(err.message)}</div>
      <button class="retry-btn" type="button" onclick="generateProblems()">もう一度試す</button>
    `;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'プリントを作る';
  }
}

document.getElementById('form').addEventListener('submit', (e) => {
  e.preventDefault();
  generateProblems();
});

loadHistory();

</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    curriculum, _ = load_curriculum()
    html = INDEX_HTML.replace("__CURRICULUM_JSON__", _build_curriculum_js(curriculum))
    return html


@app.get("/api/units")
async def list_units(grade: str):
    """指定学年の単元一覧（印刷対応のもののみ）"""
    if grade not in ALLOWED_GRADES:
        return []
    curriculum, _ = load_curriculum()
    units = curriculum["grades"].get(grade, [])
    return [
        {"id": u["id"], "name": u["name"], "category": u["category"]}
        for u in units
        if u.get("supports_print")
    ]


@app.get("/history")
async def history(limit: int = 20):
    """履歴は各ブラウザの localStorage に保存するため公開しない"""
    return []


@app.post("/generate")
async def generate(
    grade: str = Form(...),
    unit_ids: str = Form(...),
    num_questions: int = Form(8),
    difficulty: str = Form("標準"),
    answer_mode: str = Form("answer_only"),
    problem_type: str = Form("おまかせ"),
    print_style: str = Form("standard"),
    include_score: str = Form("false"),
    include_work_grid: str = Form("false"),
):
    if grade not in ALLOWED_GRADES:
        return JSONResponse({"error": "学年を選び直してください"}, status_code=400)
    if difficulty not in ALLOWED_DIFFICULTIES:
        return JSONResponse({"error": "難易度を選び直してください"}, status_code=400)
    if answer_mode not in ALLOWED_ANSWER_MODES:
        return JSONResponse({"error": "解答ページの設定を選び直してください"}, status_code=400)
    if problem_type not in ALLOWED_PROBLEM_TYPES:
        return JSONResponse({"error": "問題タイプを選び直してください"}, status_code=400)
    if num_questions not in (4, 6, 8, 10):
        return JSONResponse({"error": "問題数は4問・6問・8問・10問から選んでください"}, status_code=400)

    _, unit_index = load_curriculum()
    id_list = [s.strip() for s in unit_ids.split(",") if s.strip()]
    if not id_list:
        return JSONResponse({"error": "単元を選んでください"}, status_code=400)
    if len(id_list) > 1:
        return JSONResponse({"error": "単元は1つだけ選んでください"}, status_code=400)

    units = []
    for uid in id_list:
        u = unit_index.get(uid)
        if not u:
            return JSONResponse({"error": f"単元が見つかりません: {uid}"}, status_code=404)
        if not u.get("supports_print"):
            return JSONResponse({"error": f"この単元は印刷対応していません: {u.get('name')}"}, status_code=422)
        units.append(u)

    answer_style = answer_mode if answer_mode in ("with_steps", "with_explanation") else "answer_only"
    try:
        result = generate_from_units(units, grade=grade, num_questions=num_questions,
                                       difficulty=difficulty, answer_style=answer_style,
                                       problem_type=problem_type)
    except Exception as e:
        return JSONResponse({"error": f"問題の生成に失敗しました: {e}"}, status_code=500)

    if "questions" not in result or not result["questions"]:
        return JSONResponse({"error": "問題を生成できませんでした。再度お試しください"}, status_code=422)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unit_label = "・".join(u.get("name", "") for u in units)
    unit_safe = safe_filename(unit_label, max_len=40)
    token = uuid.uuid4().hex[:8]
    pdf_filename = f"{stamp}_{grade}_{unit_safe}_{difficulty}_{token}.pdf"
    pdf_path = OUTPUT_DIR / pdf_filename

    include_answers = answer_mode != "none"
    score_flag = (include_score or "false").lower() == "true"
    grid_flag = (include_work_grid or "false").lower() == "true"
    style_key = print_style if print_style in ALLOWED_PRINT_STYLES else "standard"
    try:
        make_pdf(result, pdf_path, grade=grade, difficulty=difficulty,
                 with_answer_page=include_answers,
                 print_style=style_key,
                 include_score=score_flag,
                 include_work_grid=grid_flag)
    except Exception as e:
        return JSONResponse({"error": f"PDF生成に失敗しました: {e}"}, status_code=500)

    save_history({
        "timestamp": stamp,
        "grade": grade,
        "unit_ids": ",".join(id_list),
        "unit_name": " + ".join(u.get("name", "") for u in units),
        "difficulty": difficulty,
        "problem_type": problem_type,
        "answer_mode": answer_mode,
        "num_questions": num_questions,
        "print_style": style_key,
        "include_score": score_flag,
        "include_work_grid": grid_flag,
        "pdf_filename": pdf_filename,
        "summary": result.get("summary"),
        "estimated_minutes": result.get("estimated_minutes"),
    })

    return {
        "unit": result.get("unit"),
        "summary": result.get("summary"),
        "estimated_minutes": result.get("estimated_minutes"),
        "questions": result.get("questions"),
        "pdf_url": f"/pdf/{quote(pdf_filename)}",
    }




@app.post("/repdf")
async def repdf(payload: dict = Body(...)):
    """編集後の result から PDF を再生成する"""
    result = payload.get("result", {})
    grade = payload.get("grade", "小5")
    difficulty = payload.get("difficulty", "標準")
    answer_mode = payload.get("answer_mode", "answer_only")
    print_style = payload.get("print_style", "standard")
    include_score = payload.get("include_score", "false")
    include_work_grid = payload.get("include_work_grid", "false")
    if grade not in ALLOWED_GRADES:
        return JSONResponse({"error": "学年が不正です"}, status_code=400)
    if difficulty not in ALLOWED_DIFFICULTIES:
        return JSONResponse({"error": "難易度が不正です"}, status_code=400)
    if answer_mode not in ALLOWED_ANSWER_MODES:
        return JSONResponse({"error": "解答ページの設定が不正です"}, status_code=400)

    include_answers = answer_mode != "none"
    score_flag = (str(include_score) or "false").lower() == "true"
    grid_flag = (str(include_work_grid) or "false").lower() == "true"
    style_key = print_style if print_style in ALLOWED_PRINT_STYLES else "standard"

    if "questions" not in result or not result["questions"]:
        return JSONResponse({"error": "問題データがありません"}, status_code=400)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unit_safe = safe_filename(result.get("unit", ""), max_len=40)
    difficulty_for_name = payload.get("difficulty", "標準")
    token = uuid.uuid4().hex[:8]
    pdf_filename = f"edit_{stamp}_{grade}_{unit_safe}_{difficulty_for_name}_{token}.pdf"
    pdf_path = OUTPUT_DIR / pdf_filename

    try:
        make_pdf(result, pdf_path, grade=grade, difficulty=difficulty,
                 with_answer_page=include_answers,
                 print_style=style_key,
                 include_score=score_flag,
                 include_work_grid=grid_flag)
    except Exception as e:
        return JSONResponse({"error": f"PDF再生成失敗: {e}"}, status_code=500)

    save_history({
        "timestamp": stamp,
        "grade": grade,
        "unit_name": result.get("unit", ""),
        "difficulty": difficulty,
        "problem_type": "編集済み",
        "answer_mode": answer_mode,
        "num_questions": len(result.get("questions", [])),
        "print_style": style_key,
        "include_score": score_flag,
        "include_work_grid": grid_flag,
        "pdf_filename": pdf_filename,
        "summary": result.get("summary"),
        "estimated_minutes": result.get("estimated_minutes"),
        "edited": True,
    })

    return {"pdf_url": f"/pdf/{quote(pdf_filename)}"}


@app.get("/pdf/{filename}")
async def download_pdf(filename: str):
    safe = filename.replace("..", "").replace("/", "").replace("\\", "")
    path = OUTPUT_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=safe)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "manacam-school", "version": "v2-unit-based"}
