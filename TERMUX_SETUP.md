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

## 📶 無線 ADB 設定

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

### Termux 模式（推薦）

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

### 範例對話

```
>>> ss
✅ Screenshot saved: /tmp/screen_1703001234.png

>>> ask 畫面上有什麼 App？
📸 Capturing screen...
🤖 Asking Gemini...

我在螢幕上看到以下 App：
- Chrome 瀏覽器
- Settings 設定
- Play Store
...

>>> tap 540 1200
✅ Tapped at (540, 1200)

>>> back
✅ Back pressed
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
