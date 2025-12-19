# 📱 Termux 安裝指南

在 Android 手機的 Termux 上運行 pyGeminiScrcpy，使用無線 ADB 自己控制自己。

## 🔧 安裝步驟

### 1. 安裝 Termux 基礎套件

```bash
# 更新套件
pkg update && pkg upgrade -y

# 安裝必要工具
pkg install python android-tools git -y

# 安裝系統依賴
pkg install dbus libdbus -y
```

### 2. 安裝 Python 套件

```bash
# 預編譯的 numpy（不要用 pip install numpy！）
pkg install python-numpy -y

# 純 Python 套件
pip install google-generativeai
```

**如果 google-generativeai 安裝失敗**（pydantic-core 編譯問題）：

```bash
# 方法 A：安裝 Rust 編譯器
pkg install rust binutils -y
pip install pydantic
pip install google-generativeai

# 方法 B：使用舊版 pydantic（更快）
pip install "pydantic<2.0"
pip install google-generativeai --no-deps
pip install httpx protobuf google-auth
```

### 3. 下載專案

```bash
cd ~
git clone https://github.com/yourusername/pyGeminiScrcpy.git
cd pyGeminiScrcpy
```

## 🔰 Shizuku 模式（推薦！不需要 WiFi）

Shizuku 讓你無需 WiFi 也能在 Termux 執行 ADB 命令。

### 安裝 Shizuku

1. 從 Play Store 或 GitHub 安裝 **Shizuku** app
2. 首次啟動 Shizuku（選擇其中一種）：
   - 用 PC 的 ADB 啟動（一次性）
   - 用無線 ADB 啟動（一次性）
   - 用 Root 權限

3. 在 Shizuku app 中：
   - 點擊「**在終端機應用中使用 Shizuku**」
   - 點擊「**導出文件**」
   - 儲存到 Download 資料夾

4. 在 Termux 設定 rish：
```bash
cd ~/pyGeminiScrcpy
python shizuku_setup.py install
python shizuku_setup.py check
```

### 使用 Shizuku 模式

```bash
# 使用 Shizuku 執行（不需要 WiFi ADB！）
python agent.py --shizuku --streaming

# 測試 Shizuku 是否正常
python shizuku_setup.py test
```

### Shizuku 優點

- ✅ **不需要 WiFi** - 隨時隨地使用
- ✅ **不需要每次配對** - 啟動 Shizuku 後即可使用
- ✅ **更快** - 直接執行命令，無網路延遲
- ✅ **穩定** - 不會因為 WiFi 斷線而失效

---

## 📶 無線 ADB 設定（備用方案）

### 啟用無線調試（Android 11+）

1. 前往 **設定 → 關於手機**
2. 點擊 **版本號碼** 7次 啟用開發者選項
3. 返回 **設定 → 系統 → 開發者選項**
4. 開啟 **USB 調試**
5. 開啟 **無線調試**

### 配對和連接

```bash
# 進入專案目錄
cd ~/pyGeminiScrcpy

# 方法 1：互動式設定
python wireless_adb.py

# 方法 2：命令列配對
# 1. 在手機上點擊「使用配對碼配對裝置」
# 2. 記下 IP:Port 和 6 位配對碼
python wireless_adb.py pair 192.168.1.100:37123 123456

# 3. 配對成功後連接（使用無線調試顯示的連接端口）
python wireless_adb.py connect 192.168.1.100:38765
```

### 自連模式（同一台手機）

```bash
# 嘗試自動連接
python wireless_adb.py self-connect

# 如果失敗，檢查已連接裝置
adb devices
```

## 🚀 運行

### 方法 1：使用 agent.py（完整 AI 功能）

```bash
# 設定 API Key
export GEMINI_API_KEY="your-api-key"

# 使用 Termux 模式運行
python agent.py --termux --streaming

# 連接到無線 ADB 裝置並運行
python agent.py --termux --connect 192.168.1.100:5555 --streaming

# 配對新裝置
python agent.py --pair

# 指定裝置序號
python agent.py --termux -s "192.168.1.100:5555" --streaming
```

### 方法 2：使用 termux_mode.py（輕量互動）

```bash
# 設定 API Key
export GEMINI_API_KEY="your-api-key"

# 運行互動模式
python termux_mode.py
```

互動命令：
- `screenshot` / `ss` - 截圖
- `tap X Y` - 點擊座標
- `swipe X1 Y1 X2 Y2` - 滑動
- `home` - 返回桌面
- `back` - 返回
- `ask <問題>` - 詢問 Gemini 關於螢幕內容
- `quit` - 退出

### agent.py Termux 模式功能

使用 `--termux` 標誌時：
- ✅ 自動使用 ADB 截圖（不需要 scrcpy 視頻流）
- ✅ 自動禁用 OpenCV GUI（因為 Termux 沒有圖形界面）
- ✅ 支援無線 ADB 配對和連接
- ✅ 同時支援 `GOOGLE_API_KEY` 和 `GEMINI_API_KEY` 環境變數
- ✅ 完整的 AI Agent 功能（思考、工具調用等）
- ✅ **每一步操作都會發送 Termux 通知！**

### 🔔 啟用通知功能

安裝 Termux:API 來獲得通知支援：

```bash
# 安裝 termux-api 套件
pkg install termux-api

# 同時需要安裝 Termux:API app
# 從 F-Droid 下載：https://f-droid.org/packages/com.termux.api/
```

通知類型：
- 💭 **Thinking** - AI 正在思考
- 👆 **Click** - 點擊操作
- ⌨️ **Type** - 輸入文字
- 📜 **Scroll** - 滾動操作
- 🚀 **Launch** - 啟動 App
- 🏠 **Home** - 返回桌面
- ◀️ **Back** - 返回鍵
- ✅ **Done** - 任務完成
- ❌ **Error** - 發生錯誤

### 範例對話（agent.py）

```
$ python agent.py --termux --streaming

📱 Termux detected, enabling ADB mode automatically
✅ Using device: 192.168.1.100:5555
Running in ADB Mode (1-2s per frame latency).
✨ Streaming mode enabled - you will see real-time thinking process

Enter instruction (or 'q' to quit): 打開 Chrome 並搜尋今天天氣

--- Turn 1 ---
💭 Thinking (streaming)...

我看到手機主畫面，有幾個 app 圖示...
我需要找到 Chrome 的圖示並點擊它。

Function call: launch_package({'package_name': 'com.android.chrome'})
ACTION: Launch package 'com.android.chrome'

--- Turn 2 ---
💭 Thinking (streaming)...

Chrome 已經打開，我看到搜尋欄...
```

## ❓ 常見問題

### Q: 找不到 ADB？
```bash
pkg install android-tools
```

### Q: 無法連接到裝置？
1. 確認 **無線調試** 已開啟
2. 確認手機和 Termux 在同一網路
3. 嘗試重新配對

### Q: pydantic-core 編譯失敗？
```bash
pkg install rust binutils
# 或使用舊版
pip install "pydantic<2.0"
```

### Q: 截圖失敗？
```bash
# 檢查 ADB 連接
adb devices

# 測試截圖
adb exec-out screencap -p > test.png
```

## 📝 注意事項

1. **Termux 模式使用 ADB 截圖**，不是即時視頻流
2. 每次截圖大約需要 0.5-1 秒
3. 不需要 OpenCV GUI 或 PyAV 依賴
4. API Key 可從 [Google AI Studio](https://aistudio.google.com/) 取得

## 🔗 相關檔案

- `wireless_adb.py` - 無線 ADB 配對/連接工具
- `termux_mode.py` - Termux 專用啟動器
- `agent.py` - 完整版 Agent（需要更多依賴）
