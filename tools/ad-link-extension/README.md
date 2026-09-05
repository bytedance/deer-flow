# DeerFlow Ad Link 擴充功能（目前是測試版）

這是一個 Chrome／Edge 瀏覽器擴充功能。它會把網頁上的品牌網址交給
DeerFlow，再由 DeerFlow 呼叫 Affiliates.One，產生你的導購連結。

## 先了解一件事

目前這個功能不是「直接雙擊就能使用」的 App。要完整使用，電腦上必須先：

1. 啟動 DeerFlow 後端。
2. 在 DeerFlow 後端設定 Affiliates.One 的新 API Key。
3. 在瀏覽器載入這個資料夾。

如果沒有 API Key，擴充功能不會產生導購連結，也不會修改網頁連結。

## 第一次安裝

### 1. 準備 API Key

請把新的 API Key 設定在 DeerFlow 後端，而不是擴充功能裡。設定名稱是：

```text
AFFILIATES_ONE_API_KEY
```

API Key 不要貼到聊天、GitHub 或瀏覽器擴充功能檔案中。

### 2. 在 Chrome 載入擴充功能

1. 開啟 Chrome。
2. 在網址列輸入 `chrome://extensions`，按 Enter。
3. 開啟右上角的「開發人員模式」。
4. 按「載入未封裝項目」。
5. 選擇這個資料夾：

   ```text
   tools\ad-link-extension
   ```

如果你使用 Edge，第三步的網址改成：

```text
edge://extensions
```

### 3. 填寫擴充功能設定

1. 在擴充功能清單找到「DeerFlow Ad Link」。
2. 按「詳細資料」。
3. 找到「擴充功能選項」。
4. DeerFlow Gateway URL 通常填：

   ```text
   http://localhost:8001
   ```

5. 在 `aff_uniq_id` 欄位填入 Affiliates.One 帳戶提供的推廣識別碼。
6. 勾選「啟用自動轉換」。
7. 按「儲存設定」。

### 4. 使用

重新載入一個包含品牌連結的網頁。擴充功能會嘗試將符合條件的連結轉成
Affiliates.One 導購連結。

## 目前會自動跳過的連結

- `mailto:` 電子郵件連結
- `javascript:` 連結
- 下載檔案連結
- 已經是 `vbtrax.com` 的導購連結
- 你在設定中加入的排除網域和網址

## 常見問題

**沒有轉換任何連結？**

請確認 DeerFlow 正在執行、瀏覽器已登入 DeerFlow、擴充功能已啟用，
而且後端已設定 `AFFILIATES_ONE_API_KEY`。

**顯示 `503` 或「API Key 尚未設定」？**

表示 DeerFlow 後端還沒有讀到 API Key。這不是擴充功能壞掉，而是後端尚未完成設定。

**我現在只想先看看，不想設定 API Key，可以嗎？**

可以。你可以先載入擴充功能和查看設定頁，但在 API Key 設定完成以前，
它不會產生真正有效的導購連結。
